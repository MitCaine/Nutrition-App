import { useCallback, useEffect, useRef, type ReactNode, type RefObject } from "react";
import {
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type ModalProps,
  type StyleProp,
  type TextStyle,
  type ViewStyle,
} from "react-native";

import {
  firstAvailableAccessibilityTarget,
  focusAccessibilityElement,
  type AccessibilityFocusRequester,
  type AccessibilityFocusTarget,
  type CancelAccessibilityFocus,
} from "./focus";

type Props = {
  visible: boolean;
  title: string;
  onRequestClose: () => void;
  children?: ReactNode;
  busy?: boolean;
  initialFocusRef?: RefObject<AccessibilityFocusTarget | null>;
  returnFocusRef?: RefObject<AccessibilityFocusTarget | null>;
  fallbackFocusRef?: RefObject<AccessibilityFocusTarget | null>;
  requestFocus?: AccessibilityFocusRequester;
  focusDelayMs?: number;
  onShow?: ModalProps["onShow"];
  animationType?: ModalProps["animationType"];
  transparent?: boolean;
  backdropStyle?: StyleProp<ViewStyle>;
  contentStyle?: StyleProp<ViewStyle>;
  scrollContentStyle?: StyleProp<ViewStyle>;
  scrollable?: boolean;
  headingStyle?: StyleProp<TextStyle>;
  testID?: string;
  dismissOnBackdropPress?: boolean;
  headerAction?: ReactNode;
};

/** Native modal semantics plus deterministic entry and return-focus behavior. */
export function AccessibleModal({
  visible,
  title,
  onRequestClose,
  children,
  initialFocusRef,
  returnFocusRef,
  fallbackFocusRef,
  requestFocus = focusAccessibilityElement,
  focusDelayMs = 60,
  onShow,
  animationType = "fade",
  transparent = true,
  backdropStyle,
  contentStyle,
  scrollContentStyle,
  scrollable = false,
  headingStyle,
  testID,
  dismissOnBackdropPress = false,
  headerAction,
}: Props) {
  const headingRef = useRef<Text>(null);
  const visibleRef = useRef(visible);
  const presented = useRef(false);
  const pendingEntryFocus = useRef<CancelAccessibilityFocus | null>(null);
  const pendingReturnFocus = useRef<CancelAccessibilityFocus | null>(null);
  const lifecycle = useRef({
    initialFocusRef,
    returnFocusRef,
    fallbackFocusRef,
    requestFocus,
    focusDelayMs,
    onShow,
  });
  visibleRef.current = visible;
  lifecycle.current = {
    initialFocusRef,
    returnFocusRef,
    fallbackFocusRef,
    requestFocus,
    focusDelayMs,
    onShow,
  };

  const requestReturnFocus = useCallback((delayMs: number) => {
    const state = lifecycle.current;
    const target = firstAvailableAccessibilityTarget(
      state.returnFocusRef?.current,
      state.fallbackFocusRef?.current,
    );
    if (target === null) return null;
    pendingReturnFocus.current?.();
    const cancel = state.requestFocus(target, { delayMs, focusKeyboardTarget: false });
    pendingReturnFocus.current = cancel;
    return cancel;
  }, []);

  useEffect(() => {
    if (visible) {
      pendingReturnFocus.current?.();
      pendingReturnFocus.current = null;
      presented.current = false;
      return;
    }
    pendingEntryFocus.current?.();
    pendingEntryFocus.current = null;
    if (presented.current) {
      presented.current = false;
      requestReturnFocus(lifecycle.current.focusDelayMs);
    }
  }, [requestReturnFocus, visible]);

  useEffect(() => () => {
    pendingEntryFocus.current?.();
    pendingEntryFocus.current = null;
    pendingReturnFocus.current?.();
    pendingReturnFocus.current = null;
    if (!presented.current) return;
    presented.current = false;
    // Zero-delay focus is synchronous by the shared requester contract. Calling
    // its cancellation releases ownership and also protects injected requesters
    // that do not honor that contract.
    const release = requestReturnFocus(0);
    release?.();
    pendingReturnFocus.current = null;
  }, [requestReturnFocus]);

  const handleShow = useCallback((event: Parameters<NonNullable<ModalProps["onShow"]>>[0]) => {
    lifecycle.current.onShow?.(event);
    if (!visibleRef.current || presented.current) return;
    presented.current = true;
    pendingEntryFocus.current?.();
    const state = lifecycle.current;
    const target = state.initialFocusRef?.current ?? headingRef.current;
    pendingEntryFocus.current = state.requestFocus(target, {
      delayMs: state.focusDelayMs,
      focusKeyboardTarget: false,
    });
  }, []);

  return (
    <Modal
      animationType={animationType}
      transparent={transparent}
      visible={visible}
      onRequestClose={onRequestClose}
      onShow={handleShow}
      statusBarTranslucent
    >
      <View style={[styles.backdrop, backdropStyle]} importantForAccessibility="yes">
        {dismissOnBackdropPress ? (
          <Pressable
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
            accessibilityLabel="Dismiss modal"
            onPress={onRequestClose}
            style={styles.backdropDismissTarget}
          />
        ) : null}
        <View
          accessibilityViewIsModal
          importantForAccessibility="yes"
          style={[styles.content, contentStyle]}
          testID={testID}
        >
          {headerAction ? (
            <View style={styles.titleRow}>
              <Text
                ref={headingRef}
                accessibilityRole="header"
                style={[styles.titleText, headingStyle]}
              >
                {title}
              </Text>
              {headerAction}
            </View>
          ) : (
            <Text
              ref={headingRef}
              accessibilityRole="header"
              style={headingStyle}
            >
              {title}
            </Text>
          )}
          {scrollable ? (
            <ScrollView
              contentContainerStyle={[styles.scrollContent, scrollContentStyle]}
              keyboardShouldPersistTaps="handled"
              style={styles.scrollBody}
            >
              {children}
            </ScrollView>
          ) : children}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { alignItems: "center", flex: 1, justifyContent: "center" },
  backdropDismissTarget: StyleSheet.absoluteFill,
  content: { maxHeight: "100%", width: "100%" },
  scrollBody: { flexShrink: 1 },
  scrollContent: { gap: 14, paddingBottom: 1 },
  titleRow: {
    alignItems: "center",
    flexDirection: "row",
    gap: 12,
    justifyContent: "space-between",
  },
  titleText: {
    flex: 1,
    minWidth: 0,
  },
});
