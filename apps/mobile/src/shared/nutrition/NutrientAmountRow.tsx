import { forwardRef, useId, useMemo, type ReactNode } from "react";
import { StyleSheet, Text, TextInput, View, type StyleProp, type TextInputProps, type TextStyle, type ViewStyle } from "react-native";

import { useAppTheme } from "../../app/theme/AppTheme";

type Props = Omit<TextInputProps, "style" | "value" | "onChangeText"> & {
  label: string;
  validationTarget: string;
  value: string;
  unit?: string | null;
  onChangeText: (value: string) => void;
  disabled?: boolean;
  action?: ReactNode;
  reviewRequired?: boolean;
  invalid?: boolean;
  error?: string | null;
  containerStyle?: StyleProp<ViewStyle>;
  inputStyle?: StyleProp<TextStyle>;
};

/** Compact, accessible amount/unit presentation shared by Food nutrient editors. */
export const NutrientAmountRow = forwardRef<TextInput, Props>(function NutrientAmountRow(
  {
    label,
    validationTarget,
    value,
    unit,
    onChangeText,
    disabled = false,
    action,
    reviewRequired = false,
    invalid = false,
    error,
    containerStyle,
    inputStyle,
    accessibilityHint,
    accessibilityState,
    editable,
    ...inputProps
  },
  ref,
) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const targetId = validationTarget.replace(/[^a-zA-Z0-9_-]/g, "-");
  const labelId = `nutrient-label-${targetId}-${id}`;
  const errorId = `nutrient-error-${targetId}-${id}`;
  const normalizedUnit = unit?.trim() ?? "";

  return (
    <View style={[styles.container, containerStyle]}>
      <Text accessibilityRole="header" nativeID={labelId} style={styles.label}>{label}</Text>
      <View style={styles.valueRow}>
        <TextInput
          {...inputProps}
          ref={ref}
          accessibilityLabel={`${label} amount`}
          accessibilityHint={accessibilityHint ?? [
            normalizedUnit ? `Value in ${normalizedUnit}` : "Enter a nutrient amount",
            reviewRequired ? "Review required." : null,
          ].filter(Boolean).join(" ")}
          accessibilityState={{ ...accessibilityState, disabled: disabled || accessibilityState?.disabled === true }}
          aria-describedby={error ? errorId : undefined}
          aria-invalid={invalid}
          aria-labelledby={labelId}
          editable={editable ?? !disabled}
          onChangeText={onChangeText}
          style={[styles.amountInput, inputStyle]}
          value={value}
        />
        {normalizedUnit ? <Text style={styles.unit}>{normalizedUnit}</Text> : null}
        {action ? <View style={styles.action}>{action}</View> : null}
      </View>
      {error ? <Text accessibilityRole="alert" nativeID={errorId} style={styles.error}>{error}</Text> : null}
    </View>
  );
});

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    amountInput: {
      backgroundColor: theme.colors.input,
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      color: theme.colors.text,
      flexShrink: 1,
      minHeight: 44,
      minWidth: 96,
      paddingHorizontal: 10,
      paddingVertical: 8,
      width: 120,
    },
    container: { gap: 4 },
    error: { color: theme.colors.errorText, fontSize: 13 },
    label: { color: theme.colors.text, fontSize: 15, fontWeight: "600" },
    unit: { color: theme.colors.text, fontWeight: "600" },
    action: { marginLeft: "auto" },
    valueRow: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", gap: 8 },
  });
}
