import { ReactNode, useRef } from "react";
import { ScrollView, type ScrollViewProps, View } from "react-native";

type Props = Omit<ScrollViewProps, "children"> & {
  children: (registerFocusTarget: (key: string) => { onFocus: () => void; onLayout: (event: { nativeEvent: { layout: { y: number } } }) => void }) => ReactNode;
};

export function KeyboardSafeScrollView({ children, ...props }: Props) {
  const scrollRef = useRef<ScrollView>(null);
  const positions = useRef<Record<string, number>>({});

  function registerFocusTarget(key: string) {
    return {
      onFocus: () => {
        const y = positions.current[key] ?? 0;
        const scrollY = y > 24 ? y - 24 : 0;
        scrollRef.current?.scrollTo({ y: scrollY, animated: true });
      },
      onLayout: (event: { nativeEvent: { layout: { y: number } } }) => {
        positions.current[key] = event.nativeEvent.layout.y;
      },
    };
  }

  return (
    <ScrollView ref={scrollRef} keyboardShouldPersistTaps="handled" {...props}>
      <View>{children(registerFocusTarget)}</View>
    </ScrollView>
  );
}
