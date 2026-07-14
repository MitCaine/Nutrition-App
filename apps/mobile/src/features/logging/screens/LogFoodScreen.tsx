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
import type { DailyLog } from "../api/types";
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
import { logEditErrorMessage } from "../utils/logEditErrors";
import { createClientRequestId } from "../utils/clientRequestId";
import { logInputSchema } from "../validation/logValidation";
import { useAppTheme } from "../../../app/theme/AppTheme";

type Props = {
  foodId: string;
  date: string;
  onCancel: () => void;
  onSaved: () => void;
  log?: DailyLog;
  initialAmount?: LogFoodInitialAmount;
};

export function LogFoodScreen({ foodId, date, onCancel, onSaved, log, initialAmount }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const editContext = useLogEditContext(log?.id ?? null);
  const revisionBacked = editContext.data?.is_revision_backed === true;
  const food = useFood(!log || editContext.data?.is_revision_backed === false ? foodId : null);
  const resolvedNutrition = useFoodResolvedNutrition(log ? null : foodId);
  const mutations = useLogMutations(date);
  const [amount, setAmount] = useState(formatInitialLogAmount(log?.amount_quantity));
  const [unit, setUnit] = useState<"serving" | "g">(log?.amount_unit ?? "serving");
  const [selectedServingId, setSelectedServingId] = useState<string | null>(
    initialEditAmountId(food.data, log),
  );
  const [selectedAmountMode, setSelectedAmountMode] = useState<"serving" | "g" | null>(
    log?.amount_unit ?? null,
  );
  const initializedCreateFoodId = useRef<string | null>(null);
  const cancelClaimedRef = useRef(false);
  // This intent exists only for this mounted create screen. Unchanged retries reuse it;
  // changed form payloads replace it, and remounting starts a separate logging action.
  const createIntentRef = useRef<{ fingerprint: string; requestId: string } | null>(null);
  const mountedRef = useRef(true);
  const submissionClaimedRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [initializationWarning, setInitializationWarning] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const servings = useMemo(
    () =>
      log
        ? editServingChoices(food.data, editContext.data)
        : createServingChoices(food.data, resolvedNutrition.data),
    [editContext.data, food.data, log, resolvedNutrition.data],
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!shouldApplyCreateLogInitialization({
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
      setSelectedServingId(
        initialEditAmountId(food.data, log, editContext.data) ??
          servings.find((serving) => serving.is_default)?.id ??
          initialServingId(food.data, log?.serving_definition_id),
      );
    }
  }, [editContext.data, food.data, log?.serving_definition_id, selectedServingId, servings]);

  function selectUnit(nextUnit: "serving" | "g") {
    setInitializationWarning(null);
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

  async function save() {
    if (submissionClaimedRef.current || cancelClaimedRef.current) {
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
    const input = buildLogInput({
      foodId,
      date,
      amount,
      unit,
      selectedServingId: resolvedServingId,
      selectedAmountMode,
    });
    const parsed = logInputSchema.safeParse(input);
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Invalid log");
      return;
    }
    if (submissionClaimedRef.current) {
      return;
    }
    submissionClaimedRef.current = true;
    setIsSubmitting(true);
    setError(null);
    try {
      if (log) {
        await mutations.updateLog.mutateAsync({ logId: log.id, input: buildLogUpdateInput(parsed.data) });
      } else {
        const fingerprint = JSON.stringify(parsed.data);
        if (createIntentRef.current?.fingerprint !== fingerprint) {
          createIntentRef.current = {
            fingerprint,
            requestId: createClientRequestId(),
          };
        }
        await mutations.createLog.mutateAsync({
          ...parsed.data,
          client_request_id: createIntentRef.current.requestId,
        });
      }
    } catch (saveError) {
      submissionClaimedRef.current = false;
      if (mountedRef.current) {
        setIsSubmitting(false);
        setError(logEditErrorMessage(
          saveError,
          log
            ? "Could not update this log. Check your connection and try again."
            : "Could not save this log. Check your connection and try again.",
        ));
      }
      return;
    }
    if (mountedRef.current) {
      onSaved();
    }
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
        {!log && food.data ? <Text accessibilityLabel={`Food source ${food.data.source_label}`} style={styles.meta}>{food.data.source_label}</Text> : null}
        <TextInput
          accessibilityHint="Enter a quantity greater than zero"
          accessibilityLabel="Amount quantity"
          placeholderTextColor={theme.colors.placeholder}
          value={amount}
          accessibilityState={{ disabled: isSubmitting }}
          editable={!isSubmitting}
          onChangeText={(value) => {
            setInitializationWarning(null);
            setAmount(value);
          }}
          keyboardType="decimal-pad"
          placeholder="Amount"
          style={[styles.input, isSubmitting && styles.disabled]}
        />
        <View accessibilityLabel="Amount unit" accessibilityRole="radiogroup" style={styles.segment}>
          <Pressable
            accessibilityLabel="Servings"
            accessibilityRole="radio"
            accessibilityState={{
              checked: unit === "serving",
              disabled: isSubmitting,
              selected: unit === "serving",
            }}
            disabled={isSubmitting}
            onPress={() => selectUnit("serving")}
            style={[styles.segmentButton, unit === "serving" && styles.active, isSubmitting && styles.disabled]}
          >
            <Text style={styles.text}>Servings</Text>
          </Pressable>
          <Pressable
            accessibilityLabel="Grams"
            accessibilityRole="radio"
            accessibilityState={{
              checked: unit === "g",
              disabled: isSubmitting,
              selected: unit === "g",
            }}
            disabled={isSubmitting}
            onPress={() => selectUnit("g")}
            style={[styles.segmentButton, unit === "g" && styles.active, isSubmitting && styles.disabled]}
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
                  disabled: isSubmitting,
                  selected: selectedServingId === serving.id,
                }}
                disabled={isSubmitting}
                onPress={() => {
                  setInitializationWarning(null);
                  setSelectedServingId(serving.id);
                  setSelectedAmountMode("serving");
                }}
                style={[styles.servingButton, selectedServingId === serving.id && styles.active, isSubmitting && styles.disabled]}
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
          <Text accessibilityLiveRegion="assertive" accessibilityRole="alert" style={styles.error}>
            {error}
          </Text>
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
  disabled: { opacity: 0.5 },
  error: { color: theme.colors.errorText },
  foodName: { color: theme.colors.text, fontSize: 18, fontWeight: "600" },
  meta: { color: theme.colors.secondaryText },
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, padding: 12 },
  keyboard: { backgroundColor: theme.colors.background, flex: 1 },
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
