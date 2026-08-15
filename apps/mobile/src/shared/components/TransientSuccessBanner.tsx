import { useEffect, useMemo, useRef } from "react";
import { StyleSheet, Text, View } from "react-native";
import { AccessiblePressable } from "../accessibility/AccessiblePressable";

import { useAppTheme } from "../../app/theme/AppTheme";
import {
  announceAccessibility,
  useAccessibilityAnnouncement,
  type AccessibilityAnnouncer,
  type AccessibilityAnnouncementKind,
} from "../accessibility/announcements";

export const SUCCESS_BANNER_DURATION_MS = 5000;

export function scheduleBannerExpiration(onExpired: () => void, durationMs = SUCCESS_BANNER_DURATION_MS) {
  const timeout = setTimeout(onExpired, durationMs);
  return () => clearTimeout(timeout);
}

export function TransientSuccessBanner({
  message,
  onExpired,
  durationMs = SUCCESS_BANNER_DURATION_MS,
  announcer = announceAccessibility,
  announcementKey,
  announcementKind = "success",
}: {
  message?: string | null;
  onExpired?: () => void;
  durationMs?: number;
  announcer?: AccessibilityAnnouncer;
  announcementKey?: string;
  announcementKind?: AccessibilityAnnouncementKind;
}) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const announce = useAccessibilityAnnouncement(announcer);
  const onExpiredRef = useRef(onExpired);
  useEffect(() => {
    onExpiredRef.current = onExpired;
  }, [onExpired]);
  useEffect(() => {
    if (!message || !onExpiredRef.current) return;
    return scheduleBannerExpiration(() => {
      onExpiredRef.current?.();
    }, durationMs);
  }, [durationMs, message]);
  useEffect(() => {
    if (!message) return;
    return announce(message, {key: announcementKey ?? `success-banner:${message}`, kind: announcementKind, priority: "polite",});  }, [announce, announcementKey, announcementKind, message]);
  if (!message) return null;

  return (
      <View style={styles.banner}>
        <Text accessibilityLiveRegion="polite" style={styles.text}>
          {message}
        </Text>

        {onExpired ? (
            <AccessiblePressable
                accessibilityLabel="Dismiss confirmation"
                onPress={onExpired}
                style={({ pressed }) => [
                  styles.dismissButton,
                  pressed && styles.dismissButtonPressed,
                ]}
            >
              <Text accessible={false} style={styles.dismissText}>
                ×
              </Text>
            </AccessiblePressable>
        ) : null}
      </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    banner: {
      alignItems: "center",
      backgroundColor: theme.colors.successBackground,
      borderColor: theme.colors.successBorder,
      borderRadius: 6,
      borderWidth: 1,
      flexDirection: "row",
      gap: 8,
      paddingLeft: 12,
      paddingRight: 4,
      paddingVertical: 4,
    },
    text: {
      color: theme.colors.successText,
      flex: 1,
      fontWeight: "700",
    },
    dismissButton: {
      borderRadius: 6,
    },
    dismissButtonPressed: {
      opacity: 0.6,
    },
    dismissText: {
      color: theme.colors.successText,
      fontSize: 24,
      lineHeight: 26,
    },
  });
}
