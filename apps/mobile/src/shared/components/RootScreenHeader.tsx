import { Ionicons } from "@expo/vector-icons";
import { useMemo } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../../app/theme/AppTheme";
import { OPEN_SETTINGS_ACCESSIBILITY_LABEL, ROOT_SCREEN_TITLES } from "./rootScreenHeaderModel";

type Props = {
  title: (typeof ROOT_SCREEN_TITLES)[keyof typeof ROOT_SCREEN_TITLES];
  onOpenSettings: () => void;
};

export function RootScreenHeader({ title, onOpenSettings }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  return (
    <View style={styles.header}>
      <Text style={styles.title}>{title}</Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={OPEN_SETTINGS_ACCESSIBILITY_LABEL}
        hitSlop={4}
        onPress={onOpenSettings}
        style={({ pressed }) => [styles.settingsButton, pressed && styles.pressed]}
      >
        <Ionicons name="settings-outline" size={24} color={theme.colors.text} />
      </Pressable>
    </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between", minHeight: 44 },
    pressed: { backgroundColor: theme.colors.pressedBackground, opacity: 0.8 },
    settingsButton: { alignItems: "center", borderRadius: 22, height: 44, justifyContent: "center", width: 44 },
    title: { color: theme.colors.text, fontSize: 32, fontWeight: "800", lineHeight: 38 },
  });
}
