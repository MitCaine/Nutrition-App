import { useEffect, useMemo, useRef, useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useFood, useFoodResolvedNutrition } from "../../foods/hooks/useFoods";
import type { DailyLog, DailyLogUpdateInput } from "../api/types";
import { useLogEditContext, useLogMutations } from "../hooks/useLogs";
import {
  buildLogInput,
  buildLogUpdateInput,
  createLogInitializationWarning,
  createServingChoices,
  editServingChoices,
  formatInitialLogAmount,
  formatServingGramWeight,
  initialEditAmountId,
  initialServingId,
  resolveCreateLogInitialization,
  shouldApplyCreateLogInitialization,
  type LogFoodInitialAmount,
} from "../utils/logFoodForm";
import { logEditErrorCode, logEditErrorMessage } from "../utils/logEditErrors";
import { createClientRequestId } from "../utils/clientRequestId";
import { isSupportedMeal, type MealType } from "../validation/logContracts";
import { logInputSchema } from "../validation/logValidation";
import { useAppTheme } from "../../../app/theme/AppTheme";
import { DatePickerModal } from "./DatePickerModal";
import {
  formatReadableDate,
  localDateToApiDate,
  parseLocalDateString,
} from "../utils/dailyLogDisplay";

type Props = {
  foodId: string;
  date: string;
  calendarRevision?: number;
  onCancel: () => void;
  onSaved: (result?: DailyLog) => void;
  log?: DailyLog;
  initialAmount?: LogFoodInitialAmount;
  initialMealType?: MealType | null;
  /** Add Food enables the shared meal and note authoring controls. */
  showMealAndNotes?: boolean;
  /** Active Add Food flows remain mounted when calendar context becomes restricted. */
  mutationEnabled?: boolean;
  /** Add Food requires an explicit renewed review when authoritative source data drifts. */
  strictSourceReview?: boolean;
  onSourceUnavailable?: () => void;
  /** Rehydrates the in-memory confirmation state after expected navigation. */
  initialDraft?: LogFoodDraft;
  /** Captures unsubmitted confirmation state without crossing the durability boundary. */
  onDraftChange?: (draft: LogFoodDraft) => void;
  /** Revision captured when this confirmation workflow first opened. */
  initialCalendarRevision?: number;
  /** Read-only history context for a Repeat proposal. */
  repeatReference?: {
    note: string | null;
    canCopyNotes: boolean;
    reuseStatus: "exact" | "equivalent" | "ambiguous" | "unavailable";
  };
  /** Restrict an existing-log edit to changing only its calendar date. */
  moveOnly?: boolean;
  /** Authoritative Today used by the restricted move destination picker. */
  moveToday?: string;
};

/**
 * In-memory state for the shared Add Food confirmation.
 *
 * This is deliberately serializable and owned by the navigation coordinator;
 * it is not persisted and may be discarded when the process terminates.
 */
export type LogFoodDraft = {
  amount: string;
  unit: "serving" | "g";
  selectedServingId: string | null;
  selectedAmountMode: "serving" | "g" | null;
  mealType: MealType | null;
  note: string;
  sourceFingerprint: string | null;
  sourceAuthority: LogFoodSourceAuthority | null;
  sourceReviewRequired: boolean;
  requestIntent: { fingerprint: string; requestId: string } | null;
};

/** Opaque server-backed authority values reviewed before confirmation. */
export type LogFoodSourceAuthority = {
  foodUpdatedAt: string | null;
  recipePublicationRevisionId: string | null;
};

export function LogFoodScreen({ foodId, date, calendarRevision, onCancel, onSaved, log, initialAmount, initialMealType, showMealAndNotes = false, mutationEnabled = true, strictSourceReview = false, onSourceUnavailable, initialDraft, onDraftChange, initialCalendarRevision, repeatReference, moveOnly = false, moveToday }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const editContext = useLogEditContext(log?.id ?? null, !moveOnly);
  const revisionBacked = editContext.data?.is_revision_backed === true;
  const nutritionEditUnavailable = Boolean(
    log && revisionBacked && editContext.data?.current_source_loggable === false,
  );
  const food = useFood(!moveOnly && (!log || editContext.data?.is_revision_backed === false) ? foodId : null);
  const resolvedNutrition = useFoodResolvedNutrition(moveOnly || log ? null : foodId);
  const mutations = useLogMutations(date);
  const [amount, setAmount] = useState(initialDraft?.amount ?? formatInitialLogAmount(log?.amount_quantity));
  const [unit, setUnit] = useState<"serving" | "g">(initialDraft?.unit ?? log?.amount_unit ?? "serving");
  const [selectedServingId, setSelectedServingId] = useState<string | null>(
    initialDraft?.selectedServingId !== undefined ? initialDraft.selectedServingId : initialEditAmountId(food.data, log),
  );
  const [selectedAmountMode, setSelectedAmountMode] = useState<"serving" | "g" | null>(
    initialDraft?.selectedAmountMode !== undefined ? initialDraft.selectedAmountMode : log?.amount_unit ?? null,
  );
  const mealAndNotesEnabled = showMealAndNotes || initialMealType !== undefined;
  const [mealType, setMealType] = useState<MealType | null>(
    initialDraft?.mealType !== undefined
      ? initialDraft.mealType
      : (log && isSupportedMeal(log.meal_type) ? log.meal_type : initialMealType ?? null),
  );
  const [mealTouched, setMealTouched] = useState(false);
  const [note, setNote] = useState(initialDraft?.note ?? log?.notes ?? "");
  const [noteTouched, setNoteTouched] = useState(false);
  const [editDate, setEditDate] = useState(date);
  const [editPickerDate, setEditPickerDate] = useState(parseLocalDateString(date) ?? new Date());
  const [editPickerOpen, setEditPickerOpen] = useState(false);
  const initializedCreateFoodId = useRef<string | null>(null);
  const restoredDraftRef = useRef(Boolean(initialDraft));
  const cancelClaimedRef = useRef(false);
  // Unchanged retries reuse this intent; changed form payloads replace it. The
  // navigation coordinator may carry it across ordinary in-process navigation.
  const createIntentRef = useRef<{ fingerprint: string; requestId: string } | null>(initialDraft?.requestIntent ?? null);
  const [requestIntent, setRequestIntent] = useState<{ fingerprint: string; requestId: string } | null>(initialDraft?.requestIntent ?? null);
  const mountedRef = useRef(true);
  const submissionClaimedRef = useRef(false);
  const initialCalendarRevisionRef = useRef<number | null>(initialCalendarRevision ?? calendarRevision ?? null);
  const [calendarContextChanged, setCalendarContextChanged] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [initializationWarning, setInitializationWarning] = useState<string | null>(
    initialDraft?.sourceReviewRequired
      ? "This Food changed. Review the current amount choices before saving."
      : repeatReference?.reuseStatus === "ambiguous"
        ? "The previous amount has multiple current matches. Choose a current amount before saving."
        : repeatReference?.reuseStatus === "unavailable"
          ? "The previous amount is no longer available. Choose a current amount before saving."
      : null,
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const sourceFingerprintRef = useRef<string | null>(initialDraft?.sourceFingerprint ?? null);
  const [sourceFingerprint, setSourceFingerprint] = useState<string | null>(initialDraft?.sourceFingerprint ?? null);
  const [sourceAuthority, setSourceAuthority] = useState<LogFoodSourceAuthority | null>(
    initialDraft?.sourceAuthority ?? null,
  );
  const [sourceReviewRequired, setSourceReviewRequired] = useState(initialDraft?.sourceReviewRequired ?? false);
  const [sourceUnavailable, setSourceUnavailable] = useState(false);
  const currentSourceAuthority = useMemo<LogFoodSourceAuthority | null>(() => {
    if (log && !editContext.data) {
      return null;
    }
    if (log && editContext.data?.current_source_loggable === false) {
      return null;
    }
    if (log) {
      if (editContext.data?.is_revision_backed && !editContext.data.current_recipe_publication_revision_id) {
        return null;
      }
      if (!editContext.data?.is_revision_backed && !food.data) {
        return null;
      }
      return {
        foodUpdatedAt: food.data?.updated_at ?? editContext.data?.current_source_food_updated_at ?? null,
        recipePublicationRevisionId:
          editContext.data?.current_recipe_publication_revision_id ?? null,
      };
    }
    if (!food.data || !resolvedNutrition.data) return null;
    return {
      foodUpdatedAt: food.data.updated_at ?? null,
      recipePublicationRevisionId: resolvedNutrition.data.recipe_publication_revision_id ?? null,
    };
  }, [editContext.data, food.data, log, resolvedNutrition.data]);
  const servings = useMemo(
    () =>
      log
        ? editServingChoices(food.data, editContext.data)
        : createServingChoices(food.data, resolvedNutrition.data),
    [editContext.data, food.data, log, resolvedNutrition.data],
  );

  useEffect(() => {
    onDraftChange?.({
      amount,
      unit,
      selectedServingId,
      selectedAmountMode,
      mealType,
      note,
      sourceFingerprint,
      sourceAuthority,
      sourceReviewRequired,
      requestIntent,
    });
  }, [amount, mealType, note, onDraftChange, requestIntent, selectedAmountMode, selectedServingId, sourceAuthority, sourceFingerprint, sourceReviewRequired, unit]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (calendarRevision === undefined) {
      return;
    }
    if (initialCalendarRevisionRef.current === null) {
      initialCalendarRevisionRef.current = calendarRevision;
      return;
    }
    if (initialCalendarRevisionRef.current !== calendarRevision) {
      setCalendarContextChanged(true);
      initialCalendarRevisionRef.current = calendarRevision;
    }
  }, [calendarRevision]);

  useEffect(() => {
    if (initialDraft || !shouldApplyCreateLogInitialization({
      isEditMode: Boolean(log),
      initializedFoodId: initializedCreateFoodId.current,
      foodId,
      authoritativeChoicesReady: Boolean(
        food.data && resolvedNutrition.data && !resolvedNutrition.isFetching,
      ),
    }) || !food.data || !resolvedNutrition.data) {
      return;
    }
    const initialization = resolveCreateLogInitialization(
      food.data,
      resolvedNutrition.data,
      initialAmount,
    );
    setAmount(initialization.form.amount);
    setUnit(initialization.form.unit);
    setSelectedServingId(initialization.form.selectedAmountId);
    setSelectedAmountMode(initialization.form.selectedAmountMode);
    setInitializationWarning(createLogInitializationWarning(initialization.outcome));
    initializedCreateFoodId.current = foodId;
  }, [food.data, foodId, initialAmount, log, resolvedNutrition.data, resolvedNutrition.isFetching]);

  useEffect(() => {
    if (!selectedServingId) {
      if (restoredDraftRef.current) {
        restoredDraftRef.current = false;
        return;
      }
      setSelectedServingId(
        initialEditAmountId(food.data, log, editContext.data) ??
          servings.find((serving) => serving.is_default)?.id ??
          initialServingId(food.data, log?.serving_definition_id),
      );
    }
    restoredDraftRef.current = false;
  }, [editContext.data, food.data, log?.serving_definition_id, selectedServingId, servings]);

  useEffect(() => {
    if ((!repeatReference && !log) || (!log && (!food.data || !resolvedNutrition.data || resolvedNutrition.isFetching))) {
      return;
    }
    if (
      log
      && editContext.data?.current_selected_amount_definition_id
      && (selectedServingId === log.serving_definition_id || selectedServingId === null)
    ) {
      setSelectedServingId(editContext.data.current_selected_amount_definition_id);
      setSelectedAmountMode(log.amount_unit);
      return;
    }
    if (
      unit === "serving" &&
      selectedAmountMode === "serving" &&
      selectedServingId !== null &&
      !servings.some((serving) => serving.id === selectedServingId)
    ) {
      setSelectedServingId(null);
      setSelectedAmountMode(null);
      setInitializationWarning(
        log
          ? "That amount is no longer available. Choose a current amount before saving this edit."
          : "That amount is no longer available. Choose a current amount before saving.",
      );
    }
  }, [editContext.data, food.data, log, repeatReference, resolvedNutrition.data, resolvedNutrition.isFetching, selectedAmountMode, selectedServingId, servings, unit]);

  useEffect(() => {
    if (
      !strictSourceReview ||
      (log && (!editContext.data || editContext.isLoading)) ||
      (!log && (!food.data || !resolvedNutrition.data || resolvedNutrition.isFetching))
    ) {
      return;
    }
    const fingerprint = log
      ? JSON.stringify(currentSourceAuthority)
      : JSON.stringify({ food: food.data, nutrition: resolvedNutrition.data });
    if (sourceFingerprintRef.current === null) {
      sourceFingerprintRef.current = fingerprint;
      setSourceFingerprint(fingerprint);
      return;
    }
    if (sourceFingerprintRef.current !== fingerprint) {
      sourceFingerprintRef.current = fingerprint;
      setSourceFingerprint(fingerprint);
      setSourceReviewRequired(true);
      setSelectedServingId(null);
      setSelectedAmountMode(null);
      setInitializationWarning("This Food changed. Review the current amount choices before saving.");
    }
  }, [currentSourceAuthority, editContext.data, editContext.isLoading, food.data, log, resolvedNutrition.data, resolvedNutrition.isFetching, strictSourceReview]);

  useEffect(() => {
    if (
      !strictSourceReview ||
      (log && (!editContext.data || editContext.isLoading)) ||
      (!log && (!food.data || !resolvedNutrition.data || resolvedNutrition.isFetching))
    ) {
      return;
    }
    const nextAuthority = currentSourceAuthority;
    if (!nextAuthority) {
      if (log && sourceAuthority !== null) {
        setSourceAuthority(null);
      }
      return;
    }
    if (sourceAuthority === null) {
      setSourceAuthority(nextAuthority);
      return;
    }
    if (
      sourceAuthority.foodUpdatedAt !== nextAuthority.foodUpdatedAt ||
      sourceAuthority.recipePublicationRevisionId !== nextAuthority.recipePublicationRevisionId
    ) {
      setSourceAuthority(nextAuthority);
      setSourceReviewRequired(true);
      setSelectedServingId(null);
      setSelectedAmountMode(null);
      setInitializationWarning("This Food changed. Review the current amount choices before saving.");
    }
  }, [currentSourceAuthority, editContext.data, editContext.isLoading, food.data, log, resolvedNutrition.data, resolvedNutrition.isFetching, sourceAuthority, strictSourceReview]);

  function selectUnit(nextUnit: "serving" | "g") {
    setInitializationWarning(null);
    setSourceReviewRequired(false);
    setUnit(nextUnit);
    setSelectedAmountMode(null);
    if (nextUnit === "serving" && !servings.some((serving) => serving.id === selectedServingId)) {
      setSelectedServingId(servings.find((serving) => serving.is_default)?.id ?? servings[0]?.id ?? null);
    }
  }

  function cancel() {
    if (submissionClaimedRef.current || cancelClaimedRef.current) {
      return;
    }
    cancelClaimedRef.current = true;
    onCancel();
  }

  async function submitUpdate(updateInput: Partial<DailyLogUpdateInput>, restrictedMove = false) {
    if (!log || submissionClaimedRef.current) {
      return;
    }
    const supportsReplayIdentity = Boolean(log.updated_at);
    let finalInput = { ...updateInput };
    if (supportsReplayIdentity) {
      const fingerprint = JSON.stringify(finalInput);
      if (createIntentRef.current?.fingerprint !== fingerprint) {
        const nextIntent = { fingerprint, requestId: createClientRequestId() };
        createIntentRef.current = nextIntent;
        setRequestIntent(nextIntent);
      }
      finalInput = {
        ...finalInput,
        client_request_id: createIntentRef.current?.requestId,
        expected_updated_at: log.updated_at,
      };
    }
    submissionClaimedRef.current = true;
    setIsSubmitting(true);
    setError(null);
    try {
      const updated = await mutations.updateLog.mutateAsync({
        logId: log.id,
        input: finalInput,
      });
      if (mountedRef.current) onSaved(updated);
    } catch (saveError) {
      submissionClaimedRef.current = false;
      if (mountedRef.current) {
        setIsSubmitting(false);
        const sourceErrorCode = logEditErrorCode(saveError);
        if (
          restrictedMove &&
          (sourceErrorCode === "stale_log_entry" ||
            sourceErrorCode === "calendar_context_changed" ||
            sourceErrorCode === "log_mutation_payload_conflict")
        ) {
          mutations.refreshDate?.(log.logged_date);
          onCancel();
          return;
        }
        if (!restrictedMove && strictSourceReview && sourceErrorCode) {
          if (sourceErrorCode === "source_food_unavailable") {
            setSourceUnavailable(true);
          }
          if (sourceErrorCode === "stale_log_source" || sourceErrorCode === "stale_log_amount") {
            setSourceUnavailable(false);
          }
          if (
            sourceErrorCode === "stale_log_source" ||
            sourceErrorCode === "stale_log_amount" ||
            sourceErrorCode === "source_food_unavailable"
          ) {
            setSourceReviewRequired(true);
            setSelectedServingId(null);
            setSelectedAmountMode(null);
            setInitializationWarning(
              sourceErrorCode === "stale_log_amount"
                ? "That amount changed. Choose a current amount before saving."
                : sourceErrorCode === "source_food_unavailable"
                  ? null
                  : "This Food changed. Review the current amount choices before saving.",
            );
            if (!log || !revisionBacked) void food.refetch();
            if (!log) void resolvedNutrition.refetch();
            if (log) void editContext.refetch();
          }
        }
        setError(logEditErrorMessage(saveError, "Could not update this log. Check your connection and try again."));
      }
    }
  }

  async function save() {
    if (submissionClaimedRef.current || cancelClaimedRef.current) {
      return;
    }
    if (!mutationEnabled) {
      setError("This date is no longer eligible for logging. No entry was created.");
      return;
    }
    if (moveOnly) {
      if (!log) {
        setError("This move requires an existing Daily Log entry.");
        return;
      }
      if (!moveToday) {
        setError("The authoritative calendar is unavailable. Review the destination again.");
        return;
      }
      if (editDate > moveToday) {
        setError("Choose Today or an earlier date for this move.");
        return;
      }
      await submitUpdate({
        logged_date: editDate,
        ...(calendarRevision === undefined ? {} : { calendar_revision: calendarRevision }),
      }, true);
      return;
    }
    const originalEditAmountId = log ? initialEditAmountId(food.data, log, editContext.data) : null;
    const editAmountChanged = Boolean(log && !nutritionEditUnavailable && (
      amount !== formatInitialLogAmount(log.amount_quantity)
      || unit !== log.amount_unit
      || selectedServingId !== originalEditAmountId
    ));
    if (repeatReference && !log && unit === "serving" && (selectedAmountMode !== "serving" || selectedServingId === null)) {
      setError("Choose a current serving before saving this repeated entry.");
      return;
    }
    if (
      log &&
      editAmountChanged &&
      revisionBacked &&
      unit === "serving" &&
      (selectedAmountMode !== unit || selectedServingId === null)
    ) {
      setError("Choose a current amount before saving this edit.");
      return;
    }
    if (strictSourceReview && sourceReviewRequired && currentSourceAuthority) {
      void resolvedNutrition.refetch();
      setError("This Food changed. Review the current amount choices before saving.");
      return;
    }
    if (!log && strictSourceReview && resolvedNutrition.isError) {
      setSourceUnavailable(true);
      setError("This Food is no longer available for logging. Return to Add Food and choose another Food.");
      return;
    }
    if (!log && (!resolvedNutrition.data || resolvedNutrition.isFetching)) {
      setError(
        resolvedNutrition.isError
          ? logEditErrorMessage(resolvedNutrition.error)
          : "Loading food amount choices.",
      );
      return;
    }
    if (log && !editContext.data) {
      setError(
        editContext.isError
          ? logEditErrorMessage(editContext.error)
          : "Loading log edit choices.",
      );
      return;
    }
    if (log && !revisionBacked && !food.data) {
      setError(food.isError ? logEditErrorMessage(food.error) : "Loading food amount choices.");
      return;
    }
    const resolvedServingId = selectedServingId ?? initialServingId(food.data, log?.serving_definition_id);
    const effectiveDate = log ? editDate : date;
    const baseInput = buildLogInput({
        foodId,
        date: effectiveDate,
        amount,
        unit,
        selectedServingId: resolvedServingId,
        selectedAmountMode,
      });
    const preserveUnsupportedLegacyMeal = Boolean(
      log && log.meal_type && !isSupportedMeal(log.meal_type) && !mealTouched,
    );
    const preserveUntouchedLegacyNote = Boolean(log && !noteTouched);
    const input = mealAndNotesEnabled
      ? {
          ...baseInput,
          ...(preserveUnsupportedLegacyMeal ? {} : { meal_type: mealType }),
          ...(preserveUntouchedLegacyNote ? {} : { notes: note }),
        }
      : baseInput;
    const reviewedAuthority = sourceAuthority ?? currentSourceAuthority;
    const inputWithCalendar = {
      ...input,
      ...(calendarRevision === undefined ? {} : { calendar_revision: calendarRevision }),
      ...(reviewedAuthority?.foodUpdatedAt === null || reviewedAuthority?.foodUpdatedAt === undefined
        ? {}
        : { source_food_updated_at: reviewedAuthority.foodUpdatedAt }),
      ...(reviewedAuthority?.recipePublicationRevisionId === null || reviewedAuthority?.recipePublicationRevisionId === undefined
        ? {}
        : { source_recipe_publication_revision_id: reviewedAuthority.recipePublicationRevisionId }),
    };
    const parsed = logInputSchema.safeParse(inputWithCalendar);
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Invalid log");
      return;
    }
    if (log) {
      let updateInput: Partial<DailyLogUpdateInput> = {
        ...buildLogUpdateInput(parsed.data),
        ...(calendarRevision === undefined ? {} : { calendar_revision: calendarRevision }),
      };
      const legacyRevisionContext =
        revisionBacked && editContext.data?.current_amount_choices === undefined;
      if (!editAmountChanged && !legacyRevisionContext) {
        const { amount_quantity: _quantity, amount_unit: _unit, serving_definition_id: _serving, ...metadataInput } = updateInput;
        updateInput = metadataInput;
      }
      await submitUpdate(updateInput);
      return;
    }
    if (submissionClaimedRef.current) {
      return;
    }
    submissionClaimedRef.current = true;
    setIsSubmitting(true);
    setError(null);
    try {
      const fingerprint = JSON.stringify(parsed.data);
      if (createIntentRef.current?.fingerprint !== fingerprint) {
        const nextIntent = {
          fingerprint,
          requestId: createClientRequestId(),
        };
        createIntentRef.current = nextIntent;
        setRequestIntent(nextIntent);
      }
      const created = await mutations.createLog.mutateAsync({
        ...parsed.data,
        client_request_id: createIntentRef.current.requestId,
        ...(calendarRevision === undefined ? {} : { calendar_revision: calendarRevision }),
      });
      if (mountedRef.current) onSaved(created);
      return;
    } catch (saveError) {
      submissionClaimedRef.current = false;
      if (mountedRef.current) {
        setIsSubmitting(false);
        const sourceErrorCode = logEditErrorCode(saveError);
        if (strictSourceReview && sourceErrorCode) {
          if (sourceErrorCode === "source_food_unavailable") {
            setSourceUnavailable(true);
          }
          if (sourceErrorCode === "stale_log_source" || sourceErrorCode === "stale_log_amount") {
            setSourceUnavailable(false);
          }
          if (
            sourceErrorCode === "stale_log_source" ||
            sourceErrorCode === "stale_log_amount" ||
            sourceErrorCode === "source_food_unavailable"
          ) {
            setSourceReviewRequired(true);
            setSelectedServingId(null);
            setSelectedAmountMode(null);
            setInitializationWarning(
              sourceErrorCode === "stale_log_amount"
                ? "That amount changed. Choose a current amount before saving."
                : sourceErrorCode === "source_food_unavailable"
                  ? null
                  : "This Food changed. Review the current amount choices before saving.",
            );
            if (!log || !revisionBacked) void food.refetch();
            if (!log) void resolvedNutrition.refetch();
            if (log) void editContext.refetch();
          }
        }
        setError(logEditErrorMessage(
          saveError,
          "Could not save this log. Check your connection and try again.",
        ));
      }
      return;
    }
  }

  if (moveOnly && log) {
    const destinationMaximum = parseLocalDateString(moveToday ?? date) ?? new Date();
    const mealLabel = log.meal_type
      ? log.meal_type.charAt(0).toUpperCase() + log.meal_type.slice(1)
      : "Unassigned";
    return (
      <KeyboardAvoidingView
        style={styles.keyboard}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        keyboardVerticalOffset={12}
      >
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.screen}>
          <View style={styles.header}>
            <Text accessibilityRole="header" style={styles.title}>Move Legacy Entry</Text>
            <Pressable
              accessibilityLabel="Cancel moving entry"
              accessibilityRole="button"
              accessibilityState={{ disabled: isSubmitting }}
              disabled={isSubmitting}
              onPress={cancel}
            >
              <Text style={styles.text}>Cancel</Text>
            </Pressable>
          </View>
          <Text style={styles.calendarNotice}>Move this entry to Today or an earlier date. The entry identity, nutrition, and metadata remain unchanged.</Text>
          <Text style={styles.foodName}>{log.food_name_snapshot ?? "Deleted food"}</Text>
          <Text style={styles.text}>Original date: {log.logged_date}</Text>
          <Text style={styles.text}>Amount: {formatInitialLogAmount(log.amount_quantity)} {log.amount_unit}</Text>
          <Text style={styles.text}>Meal: {mealLabel}</Text>
          {log.notes ? <Text style={styles.text}>Note: {log.notes}</Text> : null}
          {!log.source_food_available ? <Text style={styles.calendarNotice}>Source Food or Recipe is unavailable; this date-only move remains available.</Text> : null}
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Choose move destination date"
            disabled={isSubmitting}
            onPress={() => {
              setEditPickerDate(parseLocalDateString(editDate) ?? new Date());
              setEditPickerOpen(true);
            }}
            style={styles.dateButton}
          >
            <Text style={styles.dateButtonText}>Destination: {formatReadableDate(editDate)}</Text>
          </Pressable>
          <DatePickerModal
            date={editPickerDate}
            visible={editPickerOpen}
            maximumDate={destinationMaximum}
            onChange={setEditPickerDate}
            onCancel={() => setEditPickerOpen(false)}
            onConfirm={(selectedDate) => {
              const selected = localDateToApiDate(selectedDate);
              if (!moveToday || selected > moveToday) {
                setError("Choose Today or an earlier date for this move.");
                return;
              }
              setEditDate(selected);
              setError(null);
              setEditPickerOpen(false);
            }}
          />
          {calendarContextChanged ? (
            <Text accessibilityLiveRegion="polite" style={styles.calendarNotice}>
              The authoritative calendar changed. Your selected destination was kept; review it before saving.
            </Text>
          ) : null}
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
          <Pressable
            accessibilityHint="Moves this legacy entry without changing its nutrition or metadata"
            accessibilityLabel={isSubmitting ? "Moving legacy entry" : "Move legacy entry"}
            accessibilityRole="button"
            accessibilityState={{ disabled: isSubmitting, busy: isSubmitting }}
            disabled={isSubmitting}
            onPress={save}
            style={[styles.primaryButton, isSubmitting && styles.disabled]}
          >
            <Text style={styles.primaryText}>{isSubmitting ? "Moving..." : "Move entry"}</Text>
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    );
  }

  return (
    <KeyboardAvoidingView
      style={styles.keyboard}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      keyboardVerticalOffset={12}
    >
      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.screen}>
        <View style={styles.header}>
          <Text accessibilityRole="header" style={styles.title}>
            {log ? "Edit Log" : "Log Food"}
          </Text>
          <Pressable
            accessibilityLabel={log ? "Cancel editing" : "Cancel logging"}
            accessibilityRole="button"
            accessibilityState={{ disabled: isSubmitting }}
            disabled={isSubmitting}
            onPress={cancel}
            style={isSubmitting && styles.disabled}
          >
            <Text style={styles.text}>Cancel</Text>
          </Pressable>
        </View>
        <Text style={styles.foodName}>{log?.food_name_snapshot ?? food.data?.name ?? "Food"}</Text>
        <Text accessibilityLabel={`Log date ${date}`} style={styles.calendarNotice}>Logging for {date}</Text>
        {log ? (
          <>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Edit log date"
              onPress={() => {
                setEditPickerDate(parseLocalDateString(editDate) ?? new Date());
                setEditPickerOpen(true);
              }}
              style={styles.dateButton}
            >
              <Text style={styles.dateButtonText}>Date: {formatReadableDate(editDate)}</Text>
            </Pressable>
            <DatePickerModal
              date={editPickerDate}
              visible={editPickerOpen}
              onChange={setEditPickerDate}
              onCancel={() => setEditPickerOpen(false)}
              onConfirm={(selectedDate) => {
                setEditDate(localDateToApiDate(selectedDate));
                setEditPickerOpen(false);
              }}
            />
          </>
        ) : null}
        {calendarContextChanged ? (
          <Text accessibilityLiveRegion="polite" style={styles.calendarNotice}>
            The authoritative calendar changed. Your selected date and entered values were kept; review the calendar context before saving.
          </Text>
        ) : null}
        {!log && food.data ? <Text accessibilityLabel={`Food source ${food.data.source_label}`} style={styles.meta}>{food.data.source_label}</Text> : null}
        {mealAndNotesEnabled ? (
          <View accessibilityLabel="Meal assignment" accessibilityRole="radiogroup" style={styles.mealPicker}>
            <Text style={styles.label}>Meal</Text>
            <View style={styles.mealOptions}>
              <MealOption label="No meal" value={null} selected={mealType === null} disabled={isSubmitting} onPress={() => { setMealTouched(true); setMealType(null); }} />
              {(["breakfast", "lunch", "dinner", "snack"] as const).map((meal) => (
                <MealOption key={meal} label={meal[0].toUpperCase() + meal.slice(1)} value={meal} selected={mealType === meal} disabled={isSubmitting} onPress={() => { setMealTouched(true); setMealType(meal); }} />
              ))}
            </View>
          </View>
        ) : null}
          {nutritionEditUnavailable ? (
            <Text accessibilityLiveRegion="polite" style={styles.warningText}>
              Nutrition editing is unavailable because the current Recipe source is no longer available. Meal, note, and date edits remain available.
            </Text>
          ) : null}
        <TextInput
          accessibilityHint="Enter a quantity greater than zero"
          accessibilityLabel="Amount quantity"
          placeholderTextColor={theme.colors.placeholder}
          value={amount}
          accessibilityState={{ disabled: isSubmitting || nutritionEditUnavailable }}
          editable={!isSubmitting && !nutritionEditUnavailable}
          onChangeText={(value) => {
            setInitializationWarning(null);
            setSourceReviewRequired(false);
            setAmount(value);
          }}
          keyboardType="decimal-pad"
          placeholder="Amount"
            style={[styles.input, (isSubmitting || nutritionEditUnavailable) && styles.disabled]}
        />
        <View accessibilityLabel="Amount unit" accessibilityRole="radiogroup" style={styles.segment}>
          <Pressable
            accessibilityLabel="Servings"
            accessibilityRole="radio"
            accessibilityState={{
              checked: unit === "serving",
              disabled: isSubmitting || nutritionEditUnavailable,
              selected: unit === "serving",
            }}
            disabled={isSubmitting || nutritionEditUnavailable}
          onPress={() => selectUnit("serving")}
            style={[styles.segmentButton, unit === "serving" && styles.active, (isSubmitting || nutritionEditUnavailable) && styles.disabled]}
          >
            <Text style={styles.text}>Servings</Text>
          </Pressable>
          <Pressable
            accessibilityLabel="Grams"
            accessibilityRole="radio"
            accessibilityState={{
              checked: unit === "g",
              disabled: isSubmitting || nutritionEditUnavailable,
              selected: unit === "g",
            }}
            disabled={isSubmitting || nutritionEditUnavailable}
            onPress={() => selectUnit("g")}
            style={[styles.segmentButton, unit === "g" && styles.active, (isSubmitting || nutritionEditUnavailable) && styles.disabled]}
          >
            <Text style={styles.text}>Grams</Text>
          </Pressable>
        </View>
        {unit === "serving" && servings.length > 0 ? (
          <View accessibilityLabel="Serving amount" accessibilityRole="radiogroup" style={styles.servingList}>
            {servings.map((serving) => (
              <Pressable
                key={serving.id}
                accessibilityLabel={
                  serving.gram_weight
                    ? `${serving.label}, ${formatServingGramWeight(serving.gram_weight)}`
                    : serving.label
                }
                accessibilityRole="radio"
                accessibilityState={{
                  checked: selectedServingId === serving.id,
                  disabled: isSubmitting || nutritionEditUnavailable,
                  selected: selectedServingId === serving.id,
                }}
                disabled={isSubmitting || nutritionEditUnavailable}
                onPress={() => {
                  setInitializationWarning(null);
                  setSourceReviewRequired(false);
                  setSelectedServingId(serving.id);
                  setSelectedAmountMode("serving");
                }}
                style={[styles.servingButton, selectedServingId === serving.id && styles.active, (isSubmitting || nutritionEditUnavailable) && styles.disabled]}
              >
                <Text style={styles.text}>{serving.label}</Text>
                {serving.gram_weight ? <Text style={styles.servingMeta}>{formatServingGramWeight(serving.gram_weight)}</Text> : null}
              </Pressable>
            ))}
          </View>
        ) : null}
        {log && editContext.isLoading ? (
          <Text style={styles.servingMeta}>Loading log edit choices...</Text>
        ) : null}
        {log && editContext.isError ? (
          <Text accessibilityLiveRegion="assertive" accessibilityRole="alert" style={styles.error}>
            {logEditErrorMessage(editContext.error)}
          </Text>
        ) : null}
        {initializationWarning ? (
          <View
            accessibilityLiveRegion="polite"
            style={[styles.warning, isSubmitting && styles.disabled]}
          >
            <Text style={styles.warningText}>{initializationWarning}</Text>
            <Pressable
              accessibilityLabel="Dismiss amount notice"
              accessibilityRole="button"
              accessibilityState={{ disabled: isSubmitting }}
              disabled={isSubmitting}
              onPress={() => setInitializationWarning(null)}
            >
              <Text style={styles.warningDismiss}>Dismiss</Text>
            </Pressable>
          </View>
        ) : null}
        {error ? (
          <View>
            <Text accessibilityLiveRegion="assertive" accessibilityRole="alert" style={styles.error}>{error}</Text>
            {sourceUnavailable && onSourceUnavailable ? (
              <Pressable accessibilityRole="button" accessibilityLabel="Return to Add Food" onPress={onSourceUnavailable}>
                <Text style={styles.warningDismiss}>Return to Add Food</Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}
        {repeatReference ? (
          <View accessibilityLabel="Repeated note reference" style={styles.noteReference}>
            <Text style={styles.label}>Original note (not copied)</Text>
            {repeatReference.note ? <Text style={styles.noteReferenceText}>{repeatReference.note}</Text> : <Text style={styles.servingMeta}>No note</Text>}
            {repeatReference.note && repeatReference.canCopyNotes ? (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Copy notes"
                accessibilityState={{ disabled: isSubmitting }}
                disabled={isSubmitting}
                onPress={() => setNote(repeatReference.note ?? "")}
              >
                <Text style={styles.warningDismiss}>Copy notes</Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}
        {mealAndNotesEnabled ? (
          <TextInput
            accessibilityLabel="Notes"
            editable={!isSubmitting}
            multiline
            onChangeText={(value) => { setNoteTouched(true); setNote(value); }}
            placeholder="Optional note"
            placeholderTextColor={theme.colors.placeholder}
            style={[styles.noteInput, isSubmitting && styles.disabled]}
            value={note}
          />
        ) : null}
        <Pressable
          accessibilityHint={log ? "Updates this Daily Log entry" : "Adds this food to the Daily Log"}
          accessibilityLabel={isSubmitting ? (log ? "Updating log" : "Saving log") : (log ? "Save changes" : "Save log")}
          accessibilityRole="button"
          accessibilityState={{ disabled: isSubmitting, busy: isSubmitting }}
          disabled={isSubmitting}
          onPress={save}
          style={[styles.primaryButton, isSubmitting && styles.disabled]}
        >
          <Text style={styles.primaryText}>
            {isSubmitting ? (log ? "Updating..." : "Saving...") : (log ? "Save Changes" : "Save Log")}
          </Text>
        </Pressable>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  text: { color: theme.colors.text },
  active: { backgroundColor: theme.colors.activeBackground, borderColor: theme.colors.accent },
  calendarNotice: { color: theme.colors.secondaryText, fontSize: 14, lineHeight: 20 },
  disabled: { opacity: 0.5 },
  error: { color: theme.colors.errorText },
  foodName: { color: theme.colors.text, fontSize: 18, fontWeight: "600" },
  label: { color: theme.colors.text, fontWeight: "700" },
  meta: { color: theme.colors.secondaryText },
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, padding: 12 },
  keyboard: { backgroundColor: theme.colors.background, flex: 1 },
  mealOptions: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  mealPicker: { gap: 8 },
  noteInput: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, minHeight: 72, padding: 12, textAlignVertical: "top" },
  noteReference: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, gap: 6, padding: 10 },
  noteReferenceText: { color: theme.colors.text },
  dateButton: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, padding: 10 },
  dateButtonText: { color: theme.colors.text, fontWeight: "600" },
  primaryButton: { alignItems: "center", backgroundColor: theme.colors.accent, borderRadius: 6, padding: 14 },
  primaryText: { color: theme.colors.accentForeground, fontWeight: "700" },
  screen: { gap: 14, padding: 16, paddingBottom: 32 },
  segment: { flexDirection: "row", gap: 8 },
  segmentButton: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, padding: 10 },
  servingButton: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, gap: 2, padding: 10 },
  servingList: { gap: 8 },
  servingMeta: { color: theme.colors.secondaryText },
  title: { color: theme.colors.text, fontSize: 24, fontWeight: "700" },
  warning: { backgroundColor: theme.colors.warningBackground, borderRadius: 6, gap: 6, padding: 10 },
  warningDismiss: { color: theme.colors.warningText, fontWeight: "700" },
  warningText: { color: theme.colors.warningText, fontWeight: "600" },
}); }

function MealOption({ label, value, selected, disabled, onPress }: { label: string; value: MealType | null; selected: boolean; disabled: boolean; onPress: () => void }) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  return (
    <Pressable
      accessibilityLabel={`Meal ${value ?? "none"}`}
      accessibilityRole="radio"
      accessibilityState={{ checked: selected, disabled, selected }}
      disabled={disabled}
      onPress={onPress}
      style={[styles.segmentButton, selected && styles.active, disabled && styles.disabled]}
    >
      <Text style={styles.text}>{label}</Text>
    </Pressable>
  );
}
