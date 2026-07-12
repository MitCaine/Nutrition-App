import { Ionicons } from "@expo/vector-icons";
import { Pressable, SafeAreaView, StyleSheet, Text, View } from "react-native";

import { MAIN_TAB_ACCESSIBILITY_LABELS, type MainTab } from "./mainTabs";

const NAV_COLORS = {
  surface: "#ffffff",
  container: "#f2f4f7",
  activeBackground: "#dbeafe",
  activeForeground: "#155fa0",
  inactiveForeground: "#5f6875",
  pressedBackground: "#e5e9ef",
  border: "#e1e5ea",
} as const;

const TAB_ITEMS: Array<{
  id: MainTab;
  label: string;
  accessibilityLabel: string;
  icon: keyof typeof Ionicons.glyphMap;
  activeIcon: keyof typeof Ionicons.glyphMap;
}> = [
  { id: "foods", label: "Foods", accessibilityLabel: MAIN_TAB_ACCESSIBILITY_LABELS.foods, icon: "restaurant-outline", activeIcon: "restaurant" },
  { id: "daily-log", label: "Daily Log", accessibilityLabel: MAIN_TAB_ACCESSIBILITY_LABELS["daily-log"], icon: "calendar-outline", activeIcon: "calendar" },
  { id: "recipes", label: "Recipes", accessibilityLabel: MAIN_TAB_ACCESSIBILITY_LABELS.recipes, icon: "book-outline", activeIcon: "book" },
];

export function BottomNavigation({
  activeTab,
  onSelect,
}: {
  activeTab: MainTab;
  onSelect: (tab: MainTab) => void;
}) {
  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container} accessibilityRole="tablist">
        {TAB_ITEMS.map((item) => {
          const selected = item.id === activeTab;
          return (
            <Pressable
              key={item.id}
              accessibilityRole="tab"
              accessibilityLabel={item.accessibilityLabel}
              accessibilityState={{ selected }}
              onPress={() => onSelect(item.id)}
              style={({ pressed }) => [
                styles.tab,
                selected && styles.activeTab,
                pressed && !selected && styles.pressedTab,
              ]}
            >
              <Ionicons
                name={selected ? item.activeIcon : item.icon}
                size={18}
                color={selected ? NAV_COLORS.activeForeground : NAV_COLORS.inactiveForeground}
              />
              <Text style={[styles.label, selected ? styles.activeLabel : styles.inactiveLabel]}>
                {item.label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  activeLabel: { color: NAV_COLORS.activeForeground, fontWeight: "700" },
  activeTab: { backgroundColor: NAV_COLORS.activeBackground },
  container: {
    backgroundColor: NAV_COLORS.container,
    borderColor: NAV_COLORS.border,
    borderRadius: 22,
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: "row",
    marginHorizontal: 12,
    padding: 4,
  },
  inactiveLabel: { color: NAV_COLORS.inactiveForeground, fontWeight: "500" },
  label: { fontSize: 12 },
  pressedTab: { backgroundColor: NAV_COLORS.pressedBackground },
  safeArea: { backgroundColor: NAV_COLORS.surface, paddingBottom: 4, paddingTop: 4 },
  tab: {
    alignItems: "center",
    borderRadius: 18,
    flex: 1,
    flexDirection: "row",
    gap: 6,
    justifyContent: "center",
    minHeight: 44,
    paddingHorizontal: 8,
  },
});
