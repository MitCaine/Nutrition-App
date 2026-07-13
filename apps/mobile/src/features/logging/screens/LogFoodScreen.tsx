import { useEffect, useMemo, useState } from "react";
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

import { useFood } from "../../foods/hooks/useFoods";
import type { DailyLog } from "../api/types";
import { useLogEditContext, useLogMutations } from "../hooks/useLogs";
import {
  buildLogInput,
  buildLogUpdateInput,
  editServingChoices,
  formatInitialLogAmount,
  formatServingGramWeight,
  initialEditAmountId,
  initialServingId,
} from "../utils/logFoodForm";
import { logEditErrorMessage } from "../utils/logEditErrors";
import { logInputSchema } from "../validation/logValidation";
import { useAppTheme } from "../../../app/theme/AppTheme";

type Props = {
  foodId: string;
  date: string;
  onCancel: () => void;
  onSaved: () => void;
  log?: DailyLog;
};

export function LogFoodScreen({ foodId, date, onCancel, onSaved, log }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const editContext = useLogEditContext(log?.id ?? null);
  const revisionBacked = editContext.data?.is_revision_backed === true;
  const food = useFood(!log || editContext.data?.is_revision_backed === false ? foodId : null);
  const mutations = useLogMutations(date);
  const [amount, setAmount] = useState(formatInitialLogAmount(log?.amount_quantity));
  const [unit, setUnit] = useState<"serving" | "g">(log?.amount_unit ?? "serving");
  const [selectedServingId, setSelectedServingId] = useState<string | null>(
    initialEditAmountId(food.data, log),
  );
  const [error, setError] = useState<string | null>(null);
  const servings = useMemo(
    () => editServingChoices(food.data, editContext.data),
    [editContext.data, food.data],
  );

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
    setUnit(nextUnit);
    if (nextUnit === "serving" && !servings.some((serving) => serving.id === selectedServingId)) {
      setSelectedServingId(servings.find((serving) => serving.is_default)?.id ?? servings[0]?.id ?? null);
    }
  }

  async function save() {
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
    const input = buildLogInput({ foodId, date, amount, unit, selectedServingId: resolvedServingId });
    const parsed = logInputSchema.safeParse(input);
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Invalid log");
      return;
    }
    setError(null);
    try {
      if (log) {
        await mutations.updateLog.mutateAsync({ logId: log.id, input: buildLogUpdateInput(parsed.data) });
      } else {
        await mutations.createLog.mutateAsync(parsed.data);
      }
      onSaved();
    } catch (saveError) {
      setError(logEditErrorMessage(saveError));
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
          <Text style={styles.title}>{log ? "Edit Log" : "Log Food"}</Text>
          <Pressable onPress={onCancel}>
            <Text style={styles.text}>Cancel</Text>
          </Pressable>
        </View>
        <Text style={styles.foodName}>{log?.food_name_snapshot ?? food.data?.name ?? "Food"}</Text>
        <TextInput
          placeholderTextColor={theme.colors.placeholder}
          value={amount}
          onChangeText={setAmount}
          keyboardType="decimal-pad"
          placeholder="Amount"
          style={styles.input}
        />
        <View style={styles.segment}>
          <Pressable onPress={() => selectUnit("serving")} style={[styles.segmentButton, unit === "serving" && styles.active]}>
            <Text style={styles.text}>Servings</Text>
          </Pressable>
          <Pressable onPress={() => selectUnit("g")} style={[styles.segmentButton, unit === "g" && styles.active]}>
            <Text style={styles.text}>Grams</Text>
          </Pressable>
        </View>
        {unit === "serving" && servings.length > 0 ? (
          <View style={styles.servingList}>
            {servings.map((serving) => (
              <Pressable
                key={serving.id}
                onPress={() => setSelectedServingId(serving.id)}
                style={[styles.servingButton, selectedServingId === serving.id && styles.active]}
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
          <Text style={styles.error}>{logEditErrorMessage(editContext.error)}</Text>
        ) : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <Pressable onPress={save} style={styles.primaryButton}>
          <Text style={styles.primaryText}>{log ? "Save Changes" : "Save Log"}</Text>
        </Pressable>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  text: { color: theme.colors.text },
  active: { backgroundColor: theme.colors.activeBackground, borderColor: theme.colors.accent },
  error: { color: theme.colors.errorText },
  foodName: { color: theme.colors.text, fontSize: 18, fontWeight: "600" },
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
}); }
