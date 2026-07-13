import { useEffect, useMemo } from "react";
import { StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../../app/theme/AppTheme";

export const SUCCESS_BANNER_DURATION_MS = 5000;

export function scheduleBannerExpiration(onExpired: () => void, durationMs = SUCCESS_BANNER_DURATION_MS) {
  const timeout = setTimeout(onExpired, durationMs);
  return () => clearTimeout(timeout);
}

export function TransientSuccessBanner({
  message,
  onExpired,
  durationMs = SUCCESS_BANNER_DURATION_MS,
}: {
  message?: string | null;
  onExpired?: () => void;
  durationMs?: number;
}) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  useEffect(() => {
    if (!message || !onExpired) return;
    return scheduleBannerExpiration(onExpired, durationMs);
  }, [durationMs, message, onExpired]);
  if (!message) return null;
  return <View style={styles.banner}><Text style={styles.text}>{message}</Text></View>;
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    banner: { backgroundColor: theme.colors.successBackground, borderColor: theme.colors.successBorder, borderRadius: 6, borderWidth: 1, padding: 12 },
    text: { color: theme.colors.successText, fontWeight: "700" },
  });
}
