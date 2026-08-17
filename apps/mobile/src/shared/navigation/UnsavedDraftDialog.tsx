import { useMemo, useRef } from "react";
import { StyleSheet, Text, View, type View as NativeView } from "react-native";

import { useAppTheme } from "../../app/theme/AppTheme";
import { AccessibleModal } from "../accessibility/AccessibleModal";
import { AccessiblePressable } from "../accessibility/AccessiblePressable";

export function UnsavedDraftDialog({
  visible,
  onStay,
  onDiscard,
}: {
  visible: boolean;
  onStay: () => void;
  onDiscard: () => void;
}) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const stayRef = useRef<NativeView>(null);

  return (
    <AccessibleModal
      visible={visible}
      title="Discard unsaved changes?"
      onRequestClose={onStay}
      initialFocusRef={stayRef}
      backdropStyle={styles.backdrop}
      contentStyle={styles.card}
      headingStyle={styles.title}
      testID="unsaved-draft-dialog"
    >
      <Text style={styles.message}>
        Your unsaved changes will be lost if you leave this screen.
      </Text>

      <View style={styles.actions}>
        <AccessiblePressable
          ref={stayRef}
          accessibilityLabel="Stay and keep editing"
          accessibilityHint="Closes this message and keeps all unsaved changes."
          onPress={onStay}
          style={styles.secondaryButton}
        >
          <Text style={styles.secondaryText}>Stay</Text>
        </AccessiblePressable>

        <AccessiblePressable
          accessibilityLabel="Discard unsaved changes"
          accessibilityHint="Discards the current unsaved changes and continues navigation."
          onPress={onDiscard}
          style={styles.destructiveButton}
        >
          <Text style={styles.destructiveText}>Discard</Text>
        </AccessiblePressable>
      </View>
    </AccessibleModal>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    backdrop: {
      backgroundColor: theme.colors.modalBackdrop,
      padding: 24,
    },
    card: {
      backgroundColor: theme.colors.surface,
      borderColor: theme.colors.border,
      borderRadius: 10,
      borderWidth: 1,
      gap: 16,
      padding: 18,
    },
    title: {
      color: theme.colors.text,
      fontSize: 20,
      fontWeight: "700",
    },
    message: {
      color: theme.colors.text,
      fontSize: 16,
    },
    actions: {
      flexDirection: "row",
      flexWrap: "wrap",
      gap: 10,
      justifyContent: "flex-end",
    },
    secondaryButton: {
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      paddingHorizontal: 14,
      paddingVertical: 8,
    },
    secondaryText: {
      color: theme.colors.text,
      fontWeight: "700",
    },
    destructiveButton: {
      borderColor: theme.colors.destructive,
      borderRadius: 6,
      borderWidth: 1,
      paddingHorizontal: 14,
      paddingVertical: 8,
    },
    destructiveText: {
      color: theme.colors.destructive,
      fontWeight: "700",
    },
  });
}
