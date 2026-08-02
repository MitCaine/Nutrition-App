import { forwardRef, type ComponentProps } from "react";
import { Pressable, StyleSheet, type View } from "react-native";

type Props = ComponentProps<typeof Pressable> & {
  busy?: boolean;
};

/** Shared 44-point action target with consistent role, state, and duplicate-activation blocking. */
export const AccessiblePressable = forwardRef<View, Props>(function AccessiblePressable(
  { accessibilityRole = "button", accessibilityState, busy, disabled = false, onPress, style, ...props },
  ref,
) {
  const busyState = busy ?? Boolean(accessibilityState?.busy);
  const unavailable = disabled || busyState || accessibilityState?.disabled === true;
  const resolvedStyle: ComponentProps<typeof Pressable>["style"] = typeof style === "function"
    ? (state) => [styles.target, style(state)]
    : [styles.target, style];
  return (
    <Pressable
      {...props}
      ref={ref}
      accessibilityRole={accessibilityRole}
      accessibilityState={{ ...accessibilityState, busy: busyState, disabled: unavailable }}
      disabled={unavailable}
      onPress={unavailable ? undefined : onPress}
      style={resolvedStyle}
    />
  );
});

const styles = StyleSheet.create({
  target: {
    alignItems: "center",
    flexShrink: 1,
    justifyContent: "center",
    minHeight: 44,
    minWidth: 44,
  },
});
