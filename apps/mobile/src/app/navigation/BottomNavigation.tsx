import { Ionicons } from "@expo/vector-icons";
import { useMemo } from "react";
import { Pressable, SafeAreaView, StyleSheet, Text, View } from "react-native";
import { useAppTheme } from "../theme/AppTheme";

import { MAIN_TAB_ACCESSIBILITY_LABELS, type MainTab } from "./mainTabs";

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
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
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
                color={selected ? theme.colors.selectedNavigationForeground : theme.colors.inactiveForeground}
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

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    activeLabel: {
      color: theme.colors.selectedNavigationForeground,
      fontWeight: "700",
    },

    activeTab: {
      backgroundColor: theme.colors.selectedNavigationBackground,
      borderColor: theme.colors.primaryActionBorder,
      borderWidth: 1,
    },

    container: {
      backgroundColor: theme.colors.navigationSurface,
      borderRadius: 22,
      flexDirection: "row",
      marginHorizontal: 12,
    },

    inactiveLabel: {
      color: theme.colors.inactiveForeground,
      fontWeight: "500",
    },

    label: {
      fontSize: 12,
    },

    pressedTab: {
      backgroundColor: theme.colors.pressedBackground,
    },

    safeArea: {
      backgroundColor: theme.colors.background,
      paddingBottom: 4,
      paddingTop: 4,
    },

    tab: {
      alignItems: "center",
      borderRadius: 22,
      borderWidth: 0,
      flex: 1,
      flexDirection: "row",
      gap: 6,
      justifyContent: "center",
      minHeight: 44,
      paddingHorizontal: 8,
    },
  });
}