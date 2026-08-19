import { Ionicons } from "@expo/vector-icons";
import { useMemo, useRef, type RefObject } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../../app/theme/AppTheme";
import { useAccessibilityScreenFocus } from "../accessibility/focus";
import { OPEN_SETTINGS_ACCESSIBILITY_LABEL, ROOT_SCREEN_TITLES } from "./rootScreenHeaderModel";

export type RootScreenHeaderAction = {
  label: string;
  accessibilityLabel?: string;
  accessibilityHint?: string;
  onPress: () => void;
  disabled?: boolean;
  checked?: boolean;
};

type Props = {
  title: (typeof ROOT_SCREEN_TITLES)[keyof typeof ROOT_SCREEN_TITLES];
  onOpenSettings: () => void;
  action?: RootScreenHeaderAction;
  headingRef?: RefObject<Text | null>;
  autoFocus?: boolean;
};

export function RootScreenHeader({
  title,
  onOpenSettings,
  action,
  headingRef,
  autoFocus = true,
}: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const internalHeadingRef = useRef<Text>(null);
  const resolvedHeadingRef = headingRef ?? internalHeadingRef;
  useAccessibilityScreenFocus({ active: autoFocus, routeKey: title, targetRef: resolvedHeadingRef });
  return (
    <View style={styles.header}>
      <Text
        ref={resolvedHeadingRef}
        accessibilityRole="header"
        maxFontSizeMultiplier={1.5}
        style={styles.title}
      >
        {title}
      </Text>
      <View style={styles.actions}>
        {action ? (
          <Pressable
            accessibilityRole={action.checked === undefined ? "button" : "checkbox"}
            accessibilityLabel={action.accessibilityLabel ?? action.label}
            accessibilityHint={action.accessibilityHint}
            accessibilityState={{
              disabled: action.disabled,
              checked: action.checked,
            }}
            disabled={action.disabled}
            hitSlop={4}
            onPress={action.onPress}
            style={({ pressed }) => [
              styles.actionButton,
              action.disabled && styles.disabled,
              pressed && !action.disabled && styles.pressed,
            ]}
          >
            <Text
              maxFontSizeMultiplier={1.5}
              style={[
                styles.actionText,
                action.checked && styles.actionTextChecked,
              ]}
            >
              {action.label}
            </Text>
          </Pressable>
        ) : null}
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
    </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    actionButton: {
      alignItems: "center",
      borderRadius: 22,
      justifyContent: "center",
      minHeight: 44,
      paddingHorizontal: 12,
    },
    actionText: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: "600",
    },
    actionTextChecked: {
      fontWeight: "800",
    },
    actions: {
      alignItems: "center",
      flexDirection: "row",
    },
    disabled: {
      opacity: 0.45,
    },
    header: {
      alignItems: "center",
      flexDirection: "row",
      justifyContent: "space-between",
      minHeight: 44,
    },
    pressed: {
      backgroundColor: theme.colors.pressedBackground,
      opacity: 0.8,
    },
    settingsButton: {
      alignItems: "center",
      borderRadius: 22,
      height: 44,
      justifyContent: "center",
      width: 44,
    },
    title: {
      color: theme.colors.text,
      flexShrink: 1,
      fontSize: 32,
      fontWeight: "800",
      lineHeight: 38,
    },
  });
}
