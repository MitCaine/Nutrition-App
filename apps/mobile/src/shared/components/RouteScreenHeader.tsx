import {
  useMemo,
  type ReactNode,
  type RefObject,
} from "react";
import {
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type TextStyle,
} from "react-native";

import { useAppTheme } from "../../app/theme/AppTheme";
import { AccessiblePressable } from "../accessibility/AccessiblePressable";

type RouteScreenHeaderProps = {
  title: string;
  titleRef?: RefObject<Text | null>;
  titleStyle?: StyleProp<TextStyle>;
  leading?: ReactNode;
  trailing?: ReactNode;
};

export function RouteScreenHeader({
  title,
  titleRef,
  titleStyle,
  leading,
  trailing,
}: RouteScreenHeaderProps) {
  const theme = useAppTheme();
  const styles = useMemo(
    () => createStyles(theme),
    [theme],
  );

  return (
    <View
      testID="route-screen-header"
      style={styles.header}
    >
      {leading ? (
        <View style={styles.edge}>
          {leading}
        </View>
      ) : null}

      <Text
        ref={titleRef}
        accessibilityRole="header"
        maxFontSizeMultiplier={1.5}
        style={[
          styles.title,
          titleStyle,
        ]}
      >
        {title}
      </Text>

      {trailing ? (
        <View style={styles.edge}>
          {trailing}
        </View>
      ) : null}
    </View>
  );
}

type RouteHeaderActionProps = {
  accessibilityLabel: string;
  label: string;
  onPress: () => void;
  disabled?: boolean;
  busy?: boolean;
};

export function RouteHeaderAction({
  accessibilityLabel,
  label,
  onPress,
  disabled = false,
  busy = false,
}: RouteHeaderActionProps) {
  const theme = useAppTheme();
  const styles = useMemo(
    () => createStyles(theme),
    [theme],
  );

  return (
    <AccessiblePressable
      accessibilityLabel={accessibilityLabel}
      accessibilityRole="button"
      accessibilityState={{
        disabled,
      }}
      busy={busy}
      disabled={disabled}
      onPress={onPress}
      style={[
        styles.action,
        (disabled || busy) && styles.actionDisabled,
      ]}
    >
      <Text
        maxFontSizeMultiplier={1.5}
        style={styles.actionText}
      >
        {label}
      </Text>
    </AccessiblePressable>
  );
}

function createStyles(
  theme: ReturnType<typeof useAppTheme>,
) {
  return StyleSheet.create({
    action: {
      alignItems: "center",
      borderRadius: 8,
      justifyContent: "center",
      minHeight: 44,
      paddingHorizontal: 8,
    },
    actionDisabled: {
      opacity: 0.55,
    },
    actionText: {
      color: theme.colors.accent,
      fontSize: 16,
      fontWeight: "700",
    },
    edge: {
      flexShrink: 0,
    },
    header: {
      alignItems: "center",
      backgroundColor:
        theme.colors.background,
      flexDirection: "row",
      gap: 8,
      minHeight: 60,
      paddingHorizontal: 16,
      paddingVertical: 8,
    },
    title: {
      color: theme.colors.text,
      flex: 1,
      flexShrink: 1,
      fontSize: 24,
      fontWeight: "700",
      lineHeight: 30,
      minWidth: 0,
    },
  });
}
