import * as FileSystem from "expo-file-system";
import * as ImagePicker from "expo-image-picker";
import { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../../../app/theme/AppTheme";
import { recognizeTextFromImage } from "../../../native/ocr/NutritionOcr";
import { parseNutritionLabel } from "../api/ocrApi";
import type { NutritionConfirmationDraft } from "../api/types";
import { draftFromParsedLabel } from "../confirmation/confirmationModel";
import { acquireOcrImage, deleteCameraCapture, type OcrImageSelection, type OcrImageSource } from "../diagnostics/diagnosticsModel";

export function NutritionScanScreen({ onCancel, onReady }: {
  onCancel: () => void;
  onReady: (draft: NutritionConfirmationDraft) => void;
}) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const [status, setStatus] = useState<"idle" | "acquiring" | "recognizing" | "parsing" | "failure">("idle");
  const [message, setMessage] = useState<string | null>(null);
  const mounted = useRef(true);
  const requestId = useRef(0);
  const inFlight = useRef(false);
  const cameraSelection = useRef<OcrImageSelection | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      requestId.current += 1;
      void deleteCameraCapture(cameraSelection.current, (uri) => FileSystem.deleteAsync(uri, { idempotent: true }));
      cameraSelection.current = null;
    };
  }, []);

  const acquire = async (source: OcrImageSource) => {
    if (inFlight.current) return;
    inFlight.current = true;
    const current = ++requestId.current;
    setStatus("acquiring"); setMessage(null);
    const outcome = await acquireOcrImage(source, source === "camera" ? {
      requestPermission: ImagePicker.requestCameraPermissionsAsync,
      launch: () => ImagePicker.launchCameraAsync({ mediaTypes: ["images"], allowsEditing: false, quality: 1 }),
    } : {
      requestPermission: ImagePicker.requestMediaLibraryPermissionsAsync,
      launch: () => ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], allowsEditing: false, quality: 1 }),
    });
    if (!mounted.current || current !== requestId.current) {
      if (outcome.kind === "selected") void deleteCameraCapture(outcome.selection, (uri) => FileSystem.deleteAsync(uri, { idempotent: true }));
      inFlight.current = false;
      return;
    }
    if (outcome.kind !== "selected") {
      inFlight.current = false;
      setStatus(outcome.kind === "cancelled" ? "idle" : "failure");
      if (outcome.kind === "permissionDenied") setMessage(source === "camera" ? "Camera access is required to take a label photo." : "Photo access is required to choose a label image.");
      if (outcome.kind === "failed") setMessage("The image could not be acquired. Try again.");
      return;
    }
    cameraSelection.current = outcome.selection.source === "camera" ? outcome.selection : null;
    try {
      setStatus("recognizing");
      const recognized = await recognizeTextFromImage(outcome.selection.uri);
      if (!mounted.current || current !== requestId.current) return;
      setStatus("parsing");
      const parsed = await parseNutritionLabel(recognized);
      if (!mounted.current || current !== requestId.current) return;
      onReady(draftFromParsedLabel(parsed, source));
    } catch {
      if (mounted.current && current === requestId.current) {
        setStatus("failure");
        setMessage("The nutrition label could not be recognized or parsed. Try a clearer image.");
      }
    } finally {
      await deleteCameraCapture(cameraSelection.current, (uri) => FileSystem.deleteAsync(uri, { idempotent: true }));
      cameraSelection.current = null;
      inFlight.current = false;
    }
  };

  const busy = status === "acquiring" || status === "recognizing" || status === "parsing";
  return <View style={styles.screen}>
    <View style={styles.header}><Text style={styles.title}>Scan nutrition label</Text><Pressable disabled={busy} onPress={onCancel}><Text style={styles.link}>Cancel</Text></Pressable></View>
    <Text style={styles.body}>Choose a still photo or take one now. Recognition runs on this device; only structured text is sent for parsing.</Text>
    <Pressable accessibilityRole="button" disabled={busy} onPress={() => acquire("photo_library")} style={styles.button}><Text style={styles.buttonText}>Choose photo</Text></Pressable>
    <Pressable accessibilityRole="button" disabled={busy} onPress={() => acquire("camera")} style={styles.button}><Text style={styles.buttonText}>Take photo</Text></Pressable>
    {busy ? <View style={styles.progress}><ActivityIndicator/><Text style={styles.body}>{status === "acquiring" ? "Opening image source…" : status === "recognizing" ? "Recognizing label text…" : "Parsing nutrition values…"}</Text></View> : null}
    {message ? <Text accessibilityRole="alert" style={styles.error}>{message}</Text> : null}
  </View>;
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  body: { color: theme.colors.secondaryText, fontSize: 15, lineHeight: 21 },
  button: { alignItems: "center", backgroundColor: theme.colors.primaryActionBackground, borderRadius: 8, minHeight: 48, justifyContent: "center" },
  buttonText: { color: theme.colors.primaryActionForeground, fontSize: 16, fontWeight: "700" },
  error: { color: theme.colors.errorText },
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  link: { color: theme.colors.accent, fontSize: 16 },
  progress: { alignItems: "center", flexDirection: "row", gap: 10 },
  screen: { backgroundColor: theme.colors.background, flex: 1, gap: 16, padding: 16 },
  title: { color: theme.colors.text, fontSize: 26, fontWeight: "800" },
}); }
