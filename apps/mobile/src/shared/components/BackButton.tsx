import { useMemo } from "react";
import { Ionicons } from "@expo/vector-icons";
import { StyleSheet, Text } from "react-native";

import { useAppTheme } from "../../app/theme/AppTheme";
import { AccessiblePressable } from "../accessibility/AccessiblePressable";

type Props = {
  accessibilityLabel: string;
  disabled?: boolean;
  onPress: () => void;
};

/** Shared Settings-style back action used by nested mobile screens. */
export function BackButton({ accessibilityLabel, disabled = false, onPress }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  return (
    <AccessiblePressable
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [styles.back, pressed && styles.pressed]}
    >
      <Ionicons color={theme.colors.accent} name="chevron-back" size={24} />
      <Text style={styles.backText}>Back</Text>
    </AccessiblePressable>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    back: { alignItems: "center", alignSelf: "flex-start", borderRadius: 8, flexDirection: "row", gap: 4, paddingRight: 10 },
    backText: { color: theme.colors.accent, fontSize: 16 },
    pressed: { backgroundColor: theme.colors.pressedBackground },
  });
}
