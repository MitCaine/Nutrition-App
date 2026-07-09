import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { FoodDetailsScreen } from "../../features/foods/screens/FoodDetailsScreen";
import { FoodFormScreen } from "../../features/foods/screens/FoodFormScreen";
import { SavedFoodsScreen } from "../../features/foods/screens/SavedFoodsScreen";
import { useFood } from "../../features/foods/hooks/useFoods";
import { useDailyLogs } from "../../features/logging/hooks/useLogs";
import { DailyLogScreen } from "../../features/logging/screens/DailyLogScreen";
import { LogFoodScreen } from "../../features/logging/screens/LogFoodScreen";
import { UsdaPreviewScreen } from "../../features/usda/screens/UsdaPreviewScreen";
import { UsdaSearchScreen } from "../../features/usda/screens/UsdaSearchScreen";

type Route =
  | { name: "foods" }
  | { name: "new-food" }
  | { name: "food-detail"; foodId: string }
  | { name: "edit-food"; foodId: string }
  | { name: "log-food"; foodId: string }
  | { name: "edit-log"; logId: string }
  | { name: "usda-search" }
  | { name: "usda-preview"; fdcId: number }
  | { name: "daily-log" };

export function AppNavigator() {
  const [route, setRoute] = useState<Route>({ name: "foods" });
  const [foodQuery, setFoodQuery] = useState("");
  const [usdaQuery, setUsdaQuery] = useState("");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));

  let content;
  if (route.name === "new-food") {
    content = <FoodFormScreen onCancel={() => setRoute({ name: "foods" })} onSaved={(foodId) => setRoute({ name: "food-detail", foodId })} />;
  } else if (route.name === "food-detail") {
    content = (
      <FoodDetailsScreen
        foodId={route.foodId}
        onBack={() => setRoute({ name: "foods" })}
        onEdit={() => setRoute({ name: "edit-food", foodId: route.foodId })}
        onLog={() => setRoute({ name: "log-food", foodId: route.foodId })}
      />
    );
  } else if (route.name === "edit-food") {
    content = <EditFoodRoute foodId={route.foodId} onCancel={() => setRoute({ name: "food-detail", foodId: route.foodId })} onSaved={(foodId) => setRoute({ name: "food-detail", foodId })} />;
  } else if (route.name === "log-food") {
    content = <LogFoodScreen foodId={route.foodId} date={date} onCancel={() => setRoute({ name: "food-detail", foodId: route.foodId })} onSaved={() => setRoute({ name: "daily-log" })} />;
  } else if (route.name === "edit-log") {
    content = <EditLogRoute logId={route.logId} date={date} onCancel={() => setRoute({ name: "daily-log" })} onSaved={() => setRoute({ name: "daily-log" })} />;
  } else if (route.name === "usda-search") {
    content = (
      <UsdaSearchScreen
        query={usdaQuery}
        setQuery={setUsdaQuery}
        onBack={() => setRoute({ name: "foods" })}
        onOpenPreview={(fdcId) => setRoute({ name: "usda-preview", fdcId })}
      />
    );
  } else if (route.name === "usda-preview") {
    content = (
      <UsdaPreviewScreen
        fdcId={route.fdcId}
        onBack={() => setRoute({ name: "usda-search" })}
        onImported={(foodId) => setRoute({ name: "food-detail", foodId })}
      />
    );
  } else if (route.name === "daily-log") {
    content = <DailyLogScreen date={date} setDate={setDate} onOpenFood={(foodId) => setRoute({ name: "food-detail", foodId })} onEditLog={(logId) => setRoute({ name: "edit-log", logId })} />;
  } else {
    content = (
      <SavedFoodsScreen
        query={foodQuery}
        setQuery={setFoodQuery}
        onCreate={() => setRoute({ name: "new-food" })}
        onSearchUsda={() => setRoute({ name: "usda-search" })}
        onOpenFood={(foodId) => setRoute({ name: "food-detail", foodId })}
      />
    );
  }

  return (
    <View style={styles.shell}>
      <View style={styles.content}>{content}</View>
      <View style={styles.tabs}>
        <Pressable onPress={() => setRoute({ name: "foods" })} style={styles.tab}>
          <Text>Foods</Text>
        </Pressable>
        <Pressable onPress={() => setRoute({ name: "daily-log" })} style={styles.tab}>
          <Text>Daily Log</Text>
        </Pressable>
      </View>
    </View>
  );
}

function EditLogRoute({
  logId,
  date,
  onCancel,
  onSaved,
}: {
  logId: string;
  date: string;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const logs = useDailyLogs(date);
  const log = logs.data?.find((item) => item.id === logId);
  if (!log) {
    return (
      <View style={styles.loading}>
        <Text>Loading...</Text>
      </View>
    );
  }
  return <LogFoodScreen foodId={log.food_item_id} date={date} log={log} onCancel={onCancel} onSaved={onSaved} />;
}

function EditFoodRoute({
  foodId,
  onCancel,
  onSaved,
}: {
  foodId: string;
  onCancel: () => void;
  onSaved: (foodId: string) => void;
}) {
  const food = useFood(foodId);
  if (!food.data) {
    return (
      <View style={styles.loading}>
        <Text>Loading...</Text>
      </View>
    );
  }
  return <FoodFormScreen food={food.data} onCancel={onCancel} onSaved={onSaved} />;
}

const styles = StyleSheet.create({
  content: { flex: 1 },
  loading: { flex: 1, padding: 16 },
  shell: { flex: 1, paddingTop: 48 },
  tab: { alignItems: "center", flex: 1, padding: 12 },
  tabs: { borderTopColor: "#e7e7e7", borderTopWidth: 1, flexDirection: "row" },
});
