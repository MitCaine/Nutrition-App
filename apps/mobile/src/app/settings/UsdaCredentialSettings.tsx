import { useCallback, useEffect, useMemo, useState } from "react";
import { StyleSheet, Text, TextInput, View } from "react-native";

import { AccessiblePressable } from "../../shared/accessibility/AccessiblePressable";
import { useOptionalNutritionRuntime } from "../../runtime/NutritionRuntimeContext";
import { useAppTheme } from "../theme/AppTheme";
import {
  isUsdaCredentialConfigured,
  removeStoredUsdaCredential,
  setStoredUsdaCredential,
} from "../../runtime/local/usdaCredentialStore";

type CredentialStatus = "loading" | "configured" | "unconfigured" | "error";

export function UsdaCredentialSettings() {
  const runtime = useOptionalNutritionRuntime();
  const isLocalAuthority = runtime?.authority.kind === "local";
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const [status, setStatus] = useState<CredentialStatus>("loading");
  const [apiKey, setApiKey] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [isRemoving, setIsRemoving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    if (!isLocalAuthority) return;
    setStatus("loading");
    setMessage(null);
    try {
      setStatus((await isUsdaCredentialConfigured()) ? "configured" : "unconfigured");
    } catch {
      setStatus("error");
      setMessage("The saved USDA API key status could not be read.");
    }
  }, [isLocalAuthority]);

  useEffect(() => {
    if (!isLocalAuthority) return;
    void loadStatus();
  }, [isLocalAuthority, loadStatus]);

  const saveCredential = useCallback(async () => {
    const normalized = apiKey.trim();
    if (normalized.length === 0) {
      setMessage("Enter a USDA API key before saving.");
      return;
    }
    setIsSaving(true);
    setMessage(null);
    try {
      await setStoredUsdaCredential(normalized);
      setApiKey("");
      setStatus("configured");
      setMessage("USDA API key saved securely on this device.");
    } catch {
      setMessage("The USDA API key could not be saved. Try again.");
    } finally {
      setIsSaving(false);
    }
  }, [apiKey]);

  const removeCredential = useCallback(async () => {
    setIsRemoving(true);
    setMessage(null);
    try {
      await removeStoredUsdaCredential();
      setApiKey("");
      setStatus("unconfigured");
      setMessage("USDA API key removed from this device.");
    } catch {
      setMessage("The USDA API key could not be removed. Try again.");
    } finally {
      setIsRemoving(false);
    }
  }, []);

  if (!isLocalAuthority) return null;

  const busy = isSaving || isRemoving;
  const statusText = status === "loading"
    ? "Checking API key status…"
    : status === "configured"
    ? "API key configured"
    : status === "unconfigured"
    ? "No API key configured"
    : "API key status unavailable";

  return (
    <>
      <Text accessibilityRole="header" style={styles.sectionTitle}>USDA FoodData Central</Text>
      <View style={styles.card}>
        <Text style={styles.description}>
          Add your personal USDA FoodData Central API key to search and import USDA foods directly in local mode. The saved key is never displayed again.
        </Text>
        <Text accessibilityLiveRegion="polite" style={styles.status}>{statusText}</Text>
        <Text nativeID="usda-api-key-label" style={styles.label}>USDA API key</Text>
        <TextInput
          aria-labelledby="usda-api-key-label"
          accessibilityHint={status === "configured" ? "Entering and saving a new key replaces the currently stored key" : "Stored securely on this device"}
          autoCapitalize="none"
          autoCorrect={false}
          editable={!busy}
          onChangeText={setApiKey}
          placeholder={status === "configured" ? "Enter a replacement key" : "Enter your personal API key"}
          placeholderTextColor={theme.colors.placeholder}
          style={styles.input}
          value={apiKey}
        />
        <AccessiblePressable
          accessibilityLabel={status === "configured" ? "Replace USDA API key" : "Save USDA API key"}
          busy={isSaving}
          disabled={busy || status === "loading"}
          onPress={() => { void saveCredential(); }}
          style={({ pressed }) => [styles.primaryButton, pressed && styles.pressed, (busy || status === "loading") && styles.disabled]}
        >
          <Text style={styles.primaryButtonText}>{isSaving ? "Saving…" : status === "configured" ? "Replace API key" : "Save API key"}</Text>
        </AccessiblePressable>
        {status === "configured" ? (
          <AccessiblePressable
            accessibilityLabel="Remove USDA API key"
            busy={isRemoving}
            disabled={busy}
            onPress={() => { void removeCredential(); }}
            style={({ pressed }) => [styles.removeButton, pressed && styles.pressed, busy && styles.disabled]}
          >
            <Text style={styles.removeButtonText}>{isRemoving ? "Removing…" : "Remove API key"}</Text>
          </AccessiblePressable>
        ) : null}
        {status === "error" ? (
          <AccessiblePressable
            accessibilityLabel="Retry USDA API key status"
            disabled={busy}
            onPress={() => { void loadStatus(); }}
            style={({ pressed }) => [styles.retryButton, pressed && styles.pressed]}
          >
            <Text style={styles.retryButtonText}>Retry key status</Text>
          </AccessiblePressable>
        ) : null}
        {message ? (
          <Text accessibilityLiveRegion="polite" style={styles.message}>{message}</Text>
        ) : null}
      </View>
    </>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    card: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: 10, borderWidth: 1, gap: 10, padding: 14 },
    description: { color: theme.colors.secondaryText, fontSize: 14, lineHeight: 20 },
    disabled: { opacity: 0.6 },
    input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, minHeight: 46, paddingHorizontal: 12, paddingVertical: 10 },
    label: { color: theme.colors.text, fontSize: 15, fontWeight: "700" },
    message: { color: theme.colors.secondaryText, fontSize: 14, lineHeight: 20 },
    pressed: { opacity: 0.85 },
    primaryButton: { alignItems: "center", backgroundColor: theme.colors.accent, borderRadius: 6, minHeight: 44, justifyContent: "center", paddingHorizontal: 12, paddingVertical: 10 },
    primaryButtonText: { color: theme.colors.accentForeground, fontWeight: "700" },
    removeButton: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, minHeight: 44, justifyContent: "center", paddingHorizontal: 12, paddingVertical: 10 },
    removeButtonText: { color: theme.colors.text, fontWeight: "700" },
    retryButton: { alignItems: "center", minHeight: 44, justifyContent: "center", paddingHorizontal: 12, paddingVertical: 10 },
    retryButtonText: { color: theme.colors.accent, fontWeight: "700" },
    sectionTitle: { color: theme.colors.secondaryText, fontSize: 14, fontWeight: "700", marginTop: 8, textTransform: "uppercase" },
    status: { color: theme.colors.text, fontSize: 15, fontWeight: "700" },
  });
}
