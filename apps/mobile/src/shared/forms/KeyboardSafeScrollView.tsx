import { ReactNode, useCallback, useEffect, useRef } from "react";
import { Keyboard, ScrollView, TextInput, type KeyboardEvent, type NativeScrollEvent, type NativeSyntheticEvent, type ScrollViewProps } from "react-native";
import { createFocusTargetRegistry } from "./focusTargets";

export type FocusTargetRegistration = { ref: (input: TextInput | null) => void; onFocus: () => void };

type Props = Omit<ScrollViewProps, "children"> & {
  children: (registerFocusTarget: (key: string) => FocusTargetRegistration) => ReactNode;
};

export function KeyboardSafeScrollView({ children, onScroll, scrollEventThrottle, ...props }: Props) {
  const scrollRef = useRef<ScrollView>(null);
  const targets = useRef(createFocusTargetRegistry<TextInput>());
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

  function registerFocusTarget(key: string) {
    return {
      ref: (input: TextInput | null) => {
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
}
