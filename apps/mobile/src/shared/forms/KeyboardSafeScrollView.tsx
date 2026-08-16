import { forwardRef, type ReactNode, useCallback, useEffect, useImperativeHandle, useRef } from "react";
import { Keyboard, ScrollView, TextInput, type KeyboardEvent, type NativeScrollEvent, type NativeSyntheticEvent, type ScrollViewProps, type View } from "react-native";
import { focusAccessibilityElement, type CancelAccessibilityFocus } from "../accessibility/focus";
import { createFocusTargetRegistry } from "./focusTargets";

export type FocusTargetRegistration = { ref: (input: TextInput | View | null) => void; onFocus: () => void };

type Props = Omit<ScrollViewProps, "children"> & {
  children: (registerFocusTarget: (key: string) => FocusTargetRegistration) => ReactNode;
};

export type KeyboardSafeScrollViewHandle = {
  focusTarget: (key: string) => boolean;
};

export const KeyboardSafeScrollView = forwardRef<KeyboardSafeScrollViewHandle, Props>(function KeyboardSafeScrollView(
  { children, onScroll, scrollEventThrottle, ...props },
  ref,
) {
  const scrollRef = useRef<ScrollView>(null);
  const targets = useRef(createFocusTargetRegistry<TextInput | View>());
  const pendingAccessibilityFocus = useRef<CancelAccessibilityFocus | null>(null);
  const keyboardTop = useRef<number | null>(null);
  const scrollOffset = useRef(0);
  const focusedKey = useRef<string | null>(null);

  const revealIfObscured = useCallback((key: string) => {
    const keyboardY = keyboardTop.current;
    if (keyboardY === null) {
      return;
    }
    targets.current.withTarget(key, (target) => {
      target.measureInWindow((_x, y, _width, height) => {
        const overlap = y + height + 12 - keyboardY;
        if (overlap > 0) {
          scrollRef.current?.scrollTo({ y: scrollOffset.current + overlap, animated: true });
        }
      });
    });
  }, []);

  useEffect(() => {
    const updateKeyboardFrame = (event: KeyboardEvent) => {
      keyboardTop.current = event.endCoordinates.screenY;
      if (focusedKey.current) {
        requestAnimationFrame(() => revealIfObscured(focusedKey.current!));
      }
    };
    const willShow = Keyboard.addListener("keyboardWillShow", updateKeyboardFrame);
    const didShow = Keyboard.addListener("keyboardDidShow", updateKeyboardFrame);
    const didHide = Keyboard.addListener("keyboardDidHide", () => { keyboardTop.current = null; });
    return () => {
      willShow.remove();
      didShow.remove();
      didHide.remove();
    };
  }, [revealIfObscured]);

  useEffect(() => () => pendingAccessibilityFocus.current?.(), []);

  useImperativeHandle(ref, () => ({
    focusTarget(key: string) {
      return targets.current.withTarget(key, (target) => {
        pendingAccessibilityFocus.current?.();
        pendingAccessibilityFocus.current = focusAccessibilityElement(target);
      });
    },
  }), []);

  function registerFocusTarget(key: string) {
    return {
      ref: (input: TextInput | View | null) => {
        targets.current.assign(key, input);
      },
      onFocus: () => {
        focusedKey.current = key;
        requestAnimationFrame(() => revealIfObscured(key));
      },
    };
  }

  return (
    <ScrollView
      ref={scrollRef}
      keyboardShouldPersistTaps="handled"
      onScroll={(event: NativeSyntheticEvent<NativeScrollEvent>) => {
        scrollOffset.current = event.nativeEvent.contentOffset.y;
        onScroll?.(event);
      }}
      scrollEventThrottle={scrollEventThrottle ?? 16}
      {...props}
    >
      {children(registerFocusTarget)}
    </ScrollView>
  );
});
