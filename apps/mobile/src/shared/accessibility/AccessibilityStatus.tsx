import { useEffect, useMemo, type ComponentProps } from "react";
import { StyleSheet, Text, View, type StyleProp, type TextStyle, type ViewStyle } from "react-native";

import { useAppTheme } from "../../app/theme/AppTheme";
import { AccessiblePressable } from "./AccessiblePressable";
import type { AccessibilityAnnouncer, AccessibilityAnnouncementKind } from "./announcements";

export type AccessibilityStatusKind =
  | "loading"
  | "refreshing"
  | "stale"
  | "empty"
  | "initial-failure"
  | "retryable-failure"
  | "unavailable"
  | "busy";

type Props = {
  kind: AccessibilityStatusKind;
  message: string;
  title?: string;
  onRetry?: () => void;
  retryContext?: string;
  busy?: boolean;
  announce?: AccessibilityAnnouncer;
  announcementKey?: string;
  containerStyle?: StyleProp<ViewStyle>;
  messageStyle?: StyleProp<TextStyle>;
  actionStyle?: ComponentProps<typeof AccessiblePressable>["style"];
};

function announcementKind(kind: AccessibilityStatusKind): AccessibilityAnnouncementKind {
  if (kind === "stale") return "stale";
  if (kind === "initial-failure" || kind === "retryable-failure") return "error";
  if (kind === "unavailable") return "warning";
  return "mutation-outcome";
}

function isFailure(kind: AccessibilityStatusKind) {
  return kind === "initial-failure" || kind === "retryable-failure";
}

/** Common loading/empty/stale/error/busy presentation without owning application state. */
export function AccessibilityStatus({
  kind,
  message,
  title,
  onRetry,
  retryContext,
  busy = kind === "busy",
  announce,
  announcementKey,
  containerStyle,
  messageStyle,
  actionStyle,
}: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const shouldAnnounce = kind !== "loading" && kind !== "refreshing" && kind !== "empty";
  const liveRegion = announce
    ? "none"
    : !shouldAnnounce
    ? "none"
    : isFailure(kind)
    ? "assertive"
    : "polite";
  useEffect(() => {
    if (!announce || !shouldAnnounce) return;
    return announce(message, {
      key: announcementKey,
      kind: announcementKind(kind),
      priority: isFailure(kind) ? "assertive" : "polite",
    });
  }, [announce, announcementKey, kind, message, shouldAnnounce]);

  const retryLabel = retryContext ? `Retry ${retryContext}` : "Retry";
  return (
    <View style={[styles.container, containerStyle]}>
      {title ? <Text accessibilityRole="header" style={styles.title}>{title}</Text> : null}
      <Text
        accessibilityLabel={message}
        accessibilityLiveRegion={liveRegion}
        accessibilityRole={isFailure(kind) ? "alert" : undefined}
        accessibilityState={{ busy, disabled: busy }}
        style={[styles.message, messageStyle]}
      >
        {message}
      </Text>
      {onRetry ? (
        <AccessiblePressable
          accessibilityLabel={retryLabel}
          busy={busy}
          onPress={onRetry}
          style={actionStyle}
        >
          <Text style={styles.action}>Retry</Text>
        </AccessiblePressable>
      ) : null}
    </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    action: { color: theme.colors.accent, fontWeight: "600" },
    container: { alignItems: "flex-start", gap: 6 },
    message: { color: theme.colors.secondaryText },
    title: { color: theme.colors.text, fontWeight: "700" },
  });
}
