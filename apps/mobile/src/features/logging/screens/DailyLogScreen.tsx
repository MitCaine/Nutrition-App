import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { formatAggregatedTotal } from "../../../shared/nutrition/display";
import { useFoods } from "../../foods/hooks/useFoods";
import { useDailyLogs, useDailySummary, useLogMutations } from "../hooks/useLogs";

type Props = {
  date: string;
  setDate: (date: string) => void;
  onOpenFood: (foodId: string) => void;
  onEditLog: (logId: string) => void;
};

export function DailyLogScreen({ date, setDate, onOpenFood, onEditLog }: Props) {
  const logs = useDailyLogs(date);
  const summary = useDailySummary(date);
  const foods = useFoods("");
  const mutations = useLogMutations(date);
  const foodNames = new Map((foods.data ?? []).map((food) => [food.id, food.name]));

  return (
    <ScrollView contentContainerStyle={styles.screen}>
      <Text style={styles.title}>Daily Log</Text>
      <TextInput value={date} onChangeText={setDate} style={styles.input} />
      <Text style={styles.sectionTitle}>Totals</Text>
      {summary.data?.totals.map((total) => (
        <View key={total.nutrientId} style={styles.totalRow}>
          <Text>{total.nutrientId}</Text>
          <Text>{formatAggregatedTotal(total)}</Text>
        </View>
      ))}
      <Text style={styles.sectionTitle}>Entries</Text>
      {logs.data?.map((log) => (
        <View key={log.id} style={styles.logRow}>
          <Pressable onPress={() => onOpenFood(log.food_item_id)}>
            <Text style={styles.foodName}>{foodNames.get(log.food_item_id) ?? "Food"}</Text>
            <Text>
              {log.amount_quantity} {log.amount_unit}
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

const styles = StyleSheet.create({
  deleteText: { color: "#b42318" },
  foodName: { fontWeight: "700" },
  input: { borderColor: "#c7c7c7", borderRadius: 6, borderWidth: 1, padding: 12 },
  logRow: { borderBottomColor: "#e7e7e7", borderBottomWidth: 1, flexDirection: "row", justifyContent: "space-between", paddingVertical: 12 },
  screen: { gap: 12, padding: 16 },
  sectionTitle: { fontSize: 18, fontWeight: "700" },
  title: { fontSize: 24, fontWeight: "700" },
  totalRow: { flexDirection: "row", justifyContent: "space-between" },
});
