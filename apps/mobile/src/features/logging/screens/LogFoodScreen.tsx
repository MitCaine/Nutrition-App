import { useEffect, useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useFood } from "../../foods/hooks/useFoods";
import type { DailyLog } from "../api/types";
import { useLogMutations } from "../hooks/useLogs";
import { buildLogInput, initialServingId } from "../utils/logFoodForm";
import { logInputSchema } from "../validation/logValidation";

type Props = {
  foodId: string;
  date: string;
  onCancel: () => void;
  onSaved: () => void;
  log?: DailyLog;
};

export function LogFoodScreen({ foodId, date, onCancel, onSaved, log }: Props) {
  const food = useFood(foodId);
  const mutations = useLogMutations(date);
  const [amount, setAmount] = useState(log?.amount_quantity ? String(log.amount_quantity) : "1");
  const [unit, setUnit] = useState<"serving" | "g">(log?.amount_unit ?? "serving");
  const [selectedServingId, setSelectedServingId] = useState<string | null>(
    initialServingId(food.data, log?.serving_definition_id),
  );
  const [error, setError] = useState<string | null>(null);
  const servings = food.data?.serving_definitions ?? [];

  useEffect(() => {
    if (!selectedServingId) {
      setSelectedServingId(initialServingId(food.data, log?.serving_definition_id));
    }
  }, [food.data, log?.serving_definition_id, selectedServingId]);

  async function save() {
    const resolvedServingId = selectedServingId ?? initialServingId(food.data, log?.serving_definition_id);
    const input = buildLogInput({ foodId, date, amount, unit, selectedServingId: resolvedServingId });
    const parsed = logInputSchema.safeParse(input);
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Invalid log");
      return;
    }
    setError(null);
    if (log) {
      await mutations.updateLog.mutateAsync({ logId: log.id, input: parsed.data });
    } else {
      await mutations.createLog.mutateAsync(parsed.data);
    }
    onSaved();
  }

  return (
    <KeyboardAvoidingView
      style={styles.screen}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      keyboardVerticalOffset={12}
    >
      <View style={styles.header}>
        <Text style={styles.title}>{log ? "Edit Log" : "Log Food"}</Text>
        <Pressable onPress={onCancel}>
          <Text>Cancel</Text>
        </Pressable>
      </View>
      <Text style={styles.foodName}>{food.data?.name ?? "Food"}</Text>
      <TextInput
        value={amount}
        onChangeText={setAmount}
        keyboardType="decimal-pad"
        placeholder="Amount"
        style={styles.input}
      />
      <View style={styles.segment}>
        <Pressable onPress={() => setUnit("serving")} style={[styles.segmentButton, unit === "serving" && styles.active]}>
          <Text>Servings</Text>
        </Pressable>
        <Pressable onPress={() => setUnit("g")} style={[styles.segmentButton, unit === "g" && styles.active]}>
          <Text>Grams</Text>
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
              <Text>{serving.label}</Text>
              {serving.gram_weight ? <Text style={styles.servingMeta}>{serving.gram_weight}g</Text> : null}
            </Pressable>
          ))}
        </View>
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable onPress={save} style={styles.primaryButton}>
        <Text style={styles.primaryText}>{log ? "Save Changes" : "Save Log"}</Text>
      </Pressable>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  active: { backgroundColor: "#dfefff", borderColor: "#2878c8" },
  error: { color: "#b42318" },
  foodName: { fontSize: 18, fontWeight: "600" },
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  input: { borderColor: "#c7c7c7", borderRadius: 6, borderWidth: 1, padding: 12 },
  primaryButton: { alignItems: "center", backgroundColor: "#1f6fb2", borderRadius: 6, padding: 14 },
  primaryText: { color: "white", fontWeight: "700" },
  screen: { flex: 1, gap: 14, padding: 16 },
  segment: { flexDirection: "row", gap: 8 },
  segmentButton: { borderColor: "#c7c7c7", borderRadius: 6, borderWidth: 1, padding: 10 },
  servingButton: { borderColor: "#c7c7c7", borderRadius: 6, borderWidth: 1, gap: 2, padding: 10 },
  servingList: { gap: 8 },
  servingMeta: { color: "#666" },
  title: { fontSize: 24, fontWeight: "700" },
});
