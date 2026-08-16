import { forwardRef, useId, useMemo } from "react";
import {
  StyleSheet,
  Text,
  TextInput,
  View,
  type StyleProp,
  type TextInputProps,
  type TextStyle,
  type ViewStyle,
} from "react-native";

import { useAppTheme } from "../../app/theme/AppTheme";

type Props = Omit<TextInputProps, "style"> & {
  label: string;
  validationTarget: string;
  hint?: string;
  error?: string | null;
  required?: boolean;
  invalid?: boolean;
  disabled?: boolean;
  readOnly?: boolean;
  containerStyle?: StyleProp<ViewStyle>;
  labelStyle?: StyleProp<TextStyle>;
  inputStyle?: StyleProp<TextStyle>;
  errorStyle?: StyleProp<TextStyle>;
};

/** Persistent visible label and native association for Epic 1 text fields. */
export const LabeledField = forwardRef<TextInput, Props>(function LabeledField(
  {
    label,
    validationTarget,
    hint,
    error,
    required = false,
    invalid = Boolean(error),
    disabled = false,
    readOnly = false,
    editable,
    accessibilityLabel,
    accessibilityState,
    containerStyle,
    labelStyle,
    inputStyle,
    errorStyle,
    multiline,
    ...inputProps
  },
  ref,
) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const targetId = validationTarget.replace(/[^a-zA-Z0-9_-]/g, "-");
  const labelId = `field-label-${targetId}-${id}`;
  const errorId = `field-error-${targetId}-${id}`;
  const interactionDisabled = disabled || accessibilityState?.disabled === true;
  const notEditable = interactionDisabled || readOnly;
  const accessibilityHint = [hint, required ? "Required." : null, readOnly ? "Read only." : null]
    .filter(Boolean)
    .join(" ");
  const fieldAccessibilityLabel = accessibilityLabel ?? label;
  return (
    <View style={[styles.container, containerStyle]}>
      <Text nativeID={labelId} style={[styles.label, labelStyle]}>
        {label}{required ? " *" : ""}
      </Text>
      <TextInput
        {...inputProps}
        ref={ref}
        accessibilityLabel={fieldAccessibilityLabel}
        accessibilityHint={accessibilityHint || undefined}
        accessibilityState={{ ...accessibilityState, disabled: interactionDisabled }}
        aria-describedby={error ? errorId : undefined}
        aria-invalid={invalid}
        aria-label={fieldAccessibilityLabel}
        aria-labelledby={labelId}
        aria-readonly={readOnly}
        aria-required={required}
        editable={editable ?? !notEditable}
        multiline={multiline}
        nativeID={`field-${targetId}`}
        style={[styles.input, multiline && styles.multiline, inputStyle]}
      />
      {error ? (
        <Text
          accessibilityRole="alert"
          nativeID={errorId}
          style={[styles.error, errorStyle]}
        >
          {error}
        </Text>
      ) : null}
    </View>
  );
});

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    container: { gap: 6 },
    error: { color: theme.colors.errorText },
    input: {
      backgroundColor: theme.colors.input,
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      color: theme.colors.text,
      padding: 12,
    },
    label: { color: theme.colors.text, fontWeight: "600" },
    multiline: { minHeight: 88, textAlignVertical: "top" },
  });
}
