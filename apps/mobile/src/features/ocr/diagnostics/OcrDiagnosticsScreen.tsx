import { Ionicons } from "@expo/vector-icons";
import * as FileSystem from "expo-file-system";
import * as ImagePicker from "expo-image-picker";
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  type LayoutChangeEvent,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
} from "react-native";

import { useAppTheme } from "../../../app/theme/AppTheme";
import {
  DEFAULT_OCR_OPTIONS,
  isOcrSupported,
  normalizeOcrError,
  recognizeTextFromImage,
  type OcrRecognitionLevel,
  type OcrRecognitionOptions,
} from "../../../native/ocr/NutritionOcr";
import {
  acquireOcrImage,
  canStartRecognition,
  deleteCameraCapture,
  INITIAL_OCR_DIAGNOSTICS_STATE,
  type OcrImageSelection,
  type OcrImageSource,
  ocrDiagnosticsReducer,
  recognizeSelection,
} from "./diagnosticsModel";
import { containedImageRect, type LayoutSize, normalizedBoxToScreenRect } from "./overlayLayout";

export function OcrDiagnosticsScreen({ onBack }: { onBack: () => void }) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const [state, dispatch] = useReducer(ocrDiagnosticsReducer, INITIAL_OCR_DIAGNOSTICS_STATE);
  const [recognitionLevel, setRecognitionLevel] = useState<OcrRecognitionLevel>(DEFAULT_OCR_OPTIONS.recognitionLevel);
  const [usesLanguageCorrection, setUsesLanguageCorrection] = useState(DEFAULT_OCR_OPTIONS.usesLanguageCorrection);
  const [acquisitionMessage, setAcquisitionMessage] = useState<string | null>(null);
  const [previewSize, setPreviewSize] = useState<LayoutSize>({ width: 0, height: 0 });
  const mountedRef = useRef(true);
  const selectionRef = useRef<OcrImageSelection | null>(null);
  const selectionGenerationRef = useRef(0);
  const acquisitionInFlightRef = useRef<OcrImageSource | null>(null);
  const recognitionIdRef = useRef(0);
  const recognitionInFlightRef = useRef<number | null>(null);
  const recognizedUriRef = useRef<string | null>(null);
  const pendingCameraCleanupRef = useRef(new Map<string, OcrImageSelection>());
  const supported = isOcrSupported();
  const options: OcrRecognitionOptions = {
    recognitionLevel,
    languages: [...DEFAULT_OCR_OPTIONS.languages],
    usesLanguageCorrection,
  };

  const deleteCachedCameraFile = async (selection: OcrImageSelection) => {
    await deleteCameraCapture(selection, (uri) => FileSystem.deleteAsync(uri, { idempotent: true }));
  };

  const flushPendingCameraCleanup = () => {
    for (const [uri, selection] of pendingCameraCleanupRef.current) {
      if (uri !== recognizedUriRef.current) {
        pendingCameraCleanupRef.current.delete(uri);
        void deleteCachedCameraFile(selection);
      }
    }
  };

  const scheduleCameraCleanup = (selection: OcrImageSelection | null) => {
    if (!selection || selection.source !== "camera") {
      return;
    }
    if (selection.uri === recognizedUriRef.current) {
      pendingCameraCleanupRef.current.set(selection.uri, selection);
    } else {
      void deleteCachedCameraFile(selection);
    }
  };

  useEffect(() => () => {
    mountedRef.current = false;
    scheduleCameraCleanup(selectionRef.current);
    selectionRef.current = null;
    flushPendingCameraCleanup();
  }, []);

  const acquireImage = async (source: OcrImageSource) => {
    if (acquisitionInFlightRef.current) {
      return;
    }
    acquisitionInFlightRef.current = source;
    dispatch({ type: "acquisitionStarted", source });
    setAcquisitionMessage(null);

    const outcome = await acquireOcrImage(source, source === "camera" ? {
      requestPermission: async () => ImagePicker.requestCameraPermissionsAsync(),
      launch: async () => ImagePicker.launchCameraAsync({
        mediaTypes: ["images"],
        allowsEditing: false,
        quality: 1,
      }),
    } : {
      requestPermission: async () => ImagePicker.requestMediaLibraryPermissionsAsync(),
      launch: async () => ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        allowsEditing: false,
        quality: 1,
      }),
    });

    acquisitionInFlightRef.current = null;
    if (!mountedRef.current) {
      if (outcome.kind === "selected") {
        scheduleCameraCleanup(outcome.selection);
      }
      return;
    }
    if (outcome.kind === "selected") {
      scheduleCameraCleanup(selectionRef.current);
      selectionRef.current = outcome.selection;
      selectionGenerationRef.current += 1;
      setPreviewSize({ width: 0, height: 0 });
      dispatch({ type: "selected", selection: outcome.selection });
      return;
    }

    dispatch({ type: "acquisitionFinished", source });
    if (outcome.kind === "permissionDenied") {
      setAcquisitionMessage(source === "camera"
        ? "Camera access was denied. Allow Camera access in iOS Settings to take a label photo."
        : "Photo access was denied. Allow Photos access in iOS Settings to choose a label image.");
    } else if (outcome.kind === "failed") {
      setAcquisitionMessage(source === "camera"
        ? "The camera could not capture an image. Try again or review iOS camera permissions."
        : "The photo library could not provide an image. Try again or review iOS photo permissions.");
    }
  };

  const clearSelection = () => {
    if (state.acquisitionSource) {
      return;
    }
    scheduleCameraCleanup(selectionRef.current);
    selectionRef.current = null;
    selectionGenerationRef.current += 1;
    setAcquisitionMessage(null);
    setPreviewSize({ width: 0, height: 0 });
    dispatch({ type: "cleared" });
  };

  const runRecognition = async () => {
    const selection = selectionRef.current;
    if (!selection || recognitionInFlightRef.current !== null || acquisitionInFlightRef.current !== null) {
      return;
    }
    const request = {
      id: recognitionIdRef.current + 1,
      selectionGeneration: selectionGenerationRef.current,
    };
    recognitionIdRef.current = request.id;
    recognitionInFlightRef.current = request.id;
    recognizedUriRef.current = selection.uri;
    dispatch({ type: "recognitionStarted", request });
    try {
      const result = await recognizeSelection(selection, recognizeTextFromImage, options);
      if (mountedRef.current) {
        dispatch({ type: "recognitionSucceeded", request, result });
      }
    } catch (error) {
      if (mountedRef.current) {
        dispatch({ type: "recognitionFailed", request, error: normalizeOcrError(error) });
      }
    } finally {
      if (recognitionInFlightRef.current === request.id) {
        recognitionInFlightRef.current = null;
        recognizedUriRef.current = null;
        flushPendingCameraCleanup();
      }
    }
  };

  const acquisitionBusy = state.acquisitionSource !== null;
  const recognitionBusy = state.recognitionRequest !== null;
  const runDisabled = !supported || !canStartRecognition(state);
  const recognizedImageRect = state.result
    ? containedImageRect(previewSize, state.result.image)
    : { x: 0, y: 0, width: 0, height: 0 };

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.header}>
        <Pressable accessibilityRole="button" accessibilityLabel="Back" onPress={onBack} style={({ pressed }) => [styles.back, pressed && styles.pressed]}>
          <Ionicons name="chevron-back" size={24} color={theme.colors.accent} />
          <Text style={styles.backText}>Settings</Text>
        </Pressable>
        <Text style={styles.title}>OCR Diagnostics</Text>
        <Text style={styles.developmentBadge}>Development only</Text>
      </View>

      <Text style={styles.body}>Camera captures, selected images, and recognized text stay on this device and are not saved to app data.</Text>
      {!supported && <Text accessibilityRole="alert" accessibilityLiveRegion="assertive" style={styles.error}>OCR is unavailable. Use an iOS custom development build; Expo Go, Android, and web are unsupported.</Text>}

      <View style={styles.actions} accessibilityState={{ busy: acquisitionBusy }}>
        <ActionButton label="Choose photo" accessibilityLabel="Choose photo" onPress={() => acquireImage("photo_library")} disabled={acquisitionBusy} busy={state.acquisitionSource === "photo_library"} styles={styles} />
        <ActionButton label="Take photo" accessibilityLabel="Take photo" onPress={() => acquireImage("camera")} disabled={acquisitionBusy} busy={state.acquisitionSource === "camera"} styles={styles} />
        {state.selection && <ActionButton label="Clear" accessibilityLabel="Clear OCR image" onPress={clearSelection} disabled={acquisitionBusy} styles={styles} secondary />}
      </View>
      {acquisitionMessage && <Text accessibilityRole="alert" accessibilityLiveRegion="assertive" style={styles.error}>{acquisitionMessage}</Text>}

      {state.selection && (
        <View style={styles.card}>
          <View
            accessibilityLabel="Selected nutrition label image preview"
            onLayout={(event: LayoutChangeEvent) => setPreviewSize(event.nativeEvent.layout)}
            style={styles.previewContainer}
          >
            <Image source={{ uri: state.selection.uri }} resizeMode="contain" style={StyleSheet.absoluteFill} />
            {state.overlayEnabled && state.result && recognizedImageRect.width > 0 && (
              <View pointerEvents="none" accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={StyleSheet.absoluteFill}>
                {state.result.observations.map((observation) => {
                  const box = normalizedBoxToScreenRect(observation.boundingBox, recognizedImageRect);
                  return <View key={observation.id} testID={`ocr-overlay-${observation.id}`} style={[styles.overlayBox, box]} />;
                })}
              </View>
            )}
          </View>
          <Text style={styles.meta}>Source: {state.selection.source === "camera" ? "camera" : "photo library"}</Text>
          <Text style={styles.meta}>Picker dimensions: {state.selection.width} × {state.selection.height}px</Text>
          {state.result && <Text style={styles.meta}>Native displayed dimensions: {state.result.image.width} × {state.result.image.height}px</Text>}
          <View style={styles.optionRow}>
            <View style={styles.optionCopy}>
              <Text style={styles.optionText}>Bounding-box overlay</Text>
              <Text style={styles.meta}>Mapped to the aspect-fit image area</Text>
            </View>
            <Switch
              accessibilityLabel="Show OCR bounding boxes"
              accessibilityRole="switch"
              accessibilityState={{ checked: state.overlayEnabled }}
              value={state.overlayEnabled}
              onValueChange={(enabled) => dispatch({ type: "overlayChanged", enabled })}
            />
          </View>
        </View>
      )}

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>Options used</Text>
        <View style={styles.segmented} accessibilityRole="radiogroup">
          {(["accurate", "fast"] as const).map((level) => (
            <Pressable
              key={level}
              accessibilityRole="radio"
              accessibilityState={{ checked: recognitionLevel === level, disabled: recognitionBusy }}
              disabled={recognitionBusy}
              onPress={() => setRecognitionLevel(level)}
              style={[styles.segment, recognitionLevel === level && styles.segmentSelected]}
            >
              <Text style={styles.optionText}>{level}</Text>
            </Pressable>
          ))}
        </View>
        <View style={styles.optionRow}>
          <View style={styles.optionCopy}>
            <Text style={styles.optionText}>Language correction</Text>
            <Text style={styles.meta}>Off by default to preserve abbreviations and decimals</Text>
          </View>
          <Switch accessibilityLabel="Use OCR language correction" disabled={recognitionBusy} value={usesLanguageCorrection} onValueChange={setUsesLanguageCorrection} />
        </View>
        <Text style={styles.meta}>Languages: {DEFAULT_OCR_OPTIONS.languages.join(", ")} · minimum text height: none</Text>
      </View>

      <ActionButton
        label={state.status === "failure" ? "Retry OCR" : "Run OCR"}
        accessibilityLabel={state.status === "failure" ? "Retry OCR" : "Run OCR"}
        onPress={runRecognition}
        disabled={runDisabled}
        busy={recognitionBusy}
        styles={styles}
      />

      <View style={styles.card} accessibilityState={{ busy: recognitionBusy }}>
        <Text accessibilityLiveRegion="polite" style={styles.sectionTitle}>State: {recognitionBusy ? "recognizing" : state.status}</Text>
        {recognitionBusy && <ActivityIndicator accessibilityLabel="Recognizing text" />}
        {state.error && <Text accessibilityRole="alert" accessibilityLiveRegion="assertive" style={styles.error}>{state.error.code}: {state.error.message}</Text>}
        {state.result && (
          <>
            <Text style={styles.meta}>Native orientation applied: {String(state.result.image.orientationApplied)}</Text>
            <Text style={styles.meta}>Recognition: {state.result.recognition.recognitionLevel} · {state.result.recognition.languages.join(", ")}</Text>
            <Text style={styles.meta}>Duration: {state.result.recognition.durationMs}ms · observations: {state.result.observations.length}</Text>
            <Text accessibilityLabel={`Recognized text. ${state.result.fullText || "No text recognized"}`} selectable style={styles.fullText}>{state.result.fullText || "No text recognized"}</Text>
          </>
        )}
      </View>

      <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
        {state.result?.observations.map((observation) => (
          <View key={observation.id} style={styles.observation}>
            <Text selectable style={styles.observationText}>{observation.text}</Text>
            <Text style={styles.meta}>confidence: {observation.confidence.toFixed(4)}</Text>
            <Text style={styles.meta}>
              box: x {observation.boundingBox.x.toFixed(4)}, y {observation.boundingBox.y.toFixed(4)}, w {observation.boundingBox.width.toFixed(4)}, h {observation.boundingBox.height.toFixed(4)}
            </Text>
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

function ActionButton({ label, accessibilityLabel, onPress, disabled = false, busy = false, secondary = false, styles }: {
  label: string;
  accessibilityLabel: string;
  onPress: () => void;
  disabled?: boolean;
  busy?: boolean;
  secondary?: boolean;
  styles: ReturnType<typeof createStyles>;
}) {
  return (
    <Pressable
      accessibilityLabel={accessibilityLabel}
      accessibilityRole="button"
      accessibilityState={{ disabled, busy }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [styles.button, secondary && styles.secondaryButton, disabled && styles.disabled, pressed && styles.pressed]}
    >
      <Text style={styles.buttonText}>{label}</Text>
    </Pressable>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    actions: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
    back: { alignItems: "center", alignSelf: "flex-start", borderRadius: 8, flexDirection: "row", minHeight: 44, paddingRight: 10 },
    backText: { color: theme.colors.accent, fontSize: 16 },
    body: { color: theme.colors.secondaryText, fontSize: 15, lineHeight: 21 },
    button: { alignItems: "center", backgroundColor: theme.colors.primaryActionBackground, borderColor: theme.colors.primaryActionBorder, borderRadius: 9, borderWidth: 1, justifyContent: "center", minHeight: 46, paddingHorizontal: 16 },
    buttonText: { color: theme.colors.primaryActionForeground, fontSize: 16, fontWeight: "700" },
    card: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: 10, borderWidth: 1, gap: 10, padding: 12 },
    content: { gap: 14, padding: 16, paddingBottom: 48 },
    developmentBadge: { alignSelf: "flex-start", backgroundColor: theme.colors.warningBackground, borderRadius: 6, color: theme.colors.warningText, fontSize: 13, fontWeight: "700", overflow: "hidden", paddingHorizontal: 8, paddingVertical: 4 },
    disabled: { backgroundColor: theme.colors.disabledBackground, borderColor: theme.colors.disabledBackground, opacity: 0.8 },
    error: { color: theme.colors.errorText, fontSize: 14, lineHeight: 20 },
    fullText: { backgroundColor: theme.colors.secondarySurface, color: theme.colors.text, fontFamily: "Courier", fontSize: 13, lineHeight: 19, padding: 10 },
    header: { gap: 8 },
    meta: { color: theme.colors.secondaryText, fontSize: 13, lineHeight: 18 },
    observation: { backgroundColor: theme.colors.secondarySurface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 4, marginTop: 8, padding: 10 },
    observationText: { color: theme.colors.text, fontSize: 15, fontWeight: "600" },
    optionCopy: { flex: 1, gap: 2 },
    optionRow: { alignItems: "center", flexDirection: "row", gap: 12, justifyContent: "space-between" },
    optionText: { color: theme.colors.text, fontSize: 15, textTransform: "capitalize" },
    overlayBox: { borderColor: "#ff3b30", borderWidth: 2, position: "absolute" },
    pressed: { opacity: 0.75 },
    previewContainer: { backgroundColor: theme.colors.secondarySurface, height: 300, overflow: "hidden", position: "relative", width: "100%" },
    screen: { backgroundColor: theme.colors.background, flex: 1 },
    secondaryButton: { backgroundColor: theme.colors.secondarySurface, borderColor: theme.colors.border },
    sectionTitle: { color: theme.colors.text, fontSize: 17, fontWeight: "700" },
    segment: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 7, borderWidth: 1, flex: 1, minHeight: 42, padding: 10 },
    segmentSelected: { backgroundColor: theme.colors.activeBackground, borderColor: theme.colors.accent },
    segmented: { flexDirection: "row", gap: 8 },
    title: { color: theme.colors.text, fontSize: 30, fontWeight: "800", lineHeight: 36 },
  });
}
