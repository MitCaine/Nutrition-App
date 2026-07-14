import { Ionicons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";
import { useMemo, useReducer, useState } from "react";
import { ActivityIndicator, Image, Pressable, ScrollView, StyleSheet, Switch, Text, View } from "react-native";

import {
  DEFAULT_OCR_OPTIONS,
  isOcrSupported,
  normalizeOcrError,
  recognizeTextFromImage,
  type OcrRecognitionLevel,
  type OcrRecognitionOptions,
} from "../../../native/ocr/NutritionOcr";
import { useAppTheme } from "../../../app/theme/AppTheme";
import {
  chooseOcrImage,
  INITIAL_OCR_DIAGNOSTICS_STATE,
  ocrDiagnosticsReducer,
  recognizeSelection,
} from "./diagnosticsModel";

export function OcrDiagnosticsScreen({ onBack }: { onBack: () => void }) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const [state, dispatch] = useReducer(ocrDiagnosticsReducer, INITIAL_OCR_DIAGNOSTICS_STATE);
  const [recognitionLevel, setRecognitionLevel] = useState<OcrRecognitionLevel>(DEFAULT_OCR_OPTIONS.recognitionLevel);
  const [usesLanguageCorrection, setUsesLanguageCorrection] = useState(DEFAULT_OCR_OPTIONS.usesLanguageCorrection);
  const [selectionMessage, setSelectionMessage] = useState<string | null>(null);
  const supported = isOcrSupported();
  const options: OcrRecognitionOptions = {
    recognitionLevel,
    languages: [...DEFAULT_OCR_OPTIONS.languages],
    usesLanguageCorrection,
  };

  const selectImage = async () => {
    setSelectionMessage(null);
    try {
      const outcome = await chooseOcrImage({
        requestPermission: async () => ImagePicker.requestMediaLibraryPermissionsAsync(),
        launch: async () => ImagePicker.launchImageLibraryAsync({
          mediaTypes: ["images"],
          allowsEditing: false,
          quality: 1,
        }),
      });
      if (outcome.kind === "permissionDenied") {
        setSelectionMessage("Photo access was denied. Allow Photos access in iOS Settings to choose a label image.");
      } else if (outcome.kind === "selected") {
        dispatch({ type: "selected", selection: outcome.selection });
      }
    } catch {
      setSelectionMessage("The photo library could not be opened. Try again or review iOS photo permissions.");
    }
  };

  const runRecognition = async () => {
    dispatch({ type: "recognitionStarted" });
    try {
      const result = await recognizeSelection(state, recognizeTextFromImage, options);
      dispatch({ type: "recognitionSucceeded", result });
    } catch (error) {
      dispatch({ type: "recognitionFailed", error: normalizeOcrError(error) });
    }
  };

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

      <Text style={styles.body}>Images and recognized text stay on this device and are not saved to app data.</Text>
      {!supported && <Text style={styles.error}>OCR is unavailable. Use an iOS custom development build; Expo Go, Android, and web are unsupported.</Text>}

      <View style={styles.actions}>
        <ActionButton label={state.selection ? "Choose another image" : "Choose image"} onPress={selectImage} styles={styles} />
        {state.selection && <ActionButton label="Clear" onPress={() => dispatch({ type: "cleared" })} styles={styles} secondary />}
      </View>
      {selectionMessage && <Text style={styles.error}>{selectionMessage}</Text>}

      {state.selection && (
        <View style={styles.card}>
          <Image source={{ uri: state.selection.uri }} resizeMode="contain" style={styles.preview} />
          <Text style={styles.meta}>Selected image: {state.selection.width} × {state.selection.height}px</Text>
        </View>
      )}

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>Options used</Text>
        <View style={styles.segmented}>
          {(["accurate", "fast"] as const).map((level) => (
            <Pressable
              key={level}
              accessibilityRole="radio"
              accessibilityState={{ checked: recognitionLevel === level }}
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
          <Switch value={usesLanguageCorrection} onValueChange={setUsesLanguageCorrection} />
        </View>
        <Text style={styles.meta}>Languages: {DEFAULT_OCR_OPTIONS.languages.join(", ")} · minimum text height: none</Text>
      </View>

      <ActionButton
        label={state.status === "failure" ? "Retry OCR" : "Run OCR"}
        onPress={runRecognition}
        disabled={!supported || !state.selection || state.status === "recognizing"}
        styles={styles}
      />

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>State: {state.status}</Text>
        {state.status === "recognizing" && <ActivityIndicator accessibilityLabel="Recognizing text" />}
        {state.error && <Text style={styles.error}>{state.error.code}: {state.error.message}</Text>}
        {state.result && (
          <>
            <Text style={styles.meta}>
              Recognized image: {state.result.image.width} × {state.result.image.height}px · orientation applied: {String(state.result.image.orientationApplied)}
            </Text>
            <Text style={styles.meta}>Duration: {state.result.recognition.durationMs}ms · observations: {state.result.observations.length}</Text>
            <Text selectable style={styles.fullText}>{state.result.fullText || "No text recognized"}</Text>
          </>
        )}
      </View>

      {state.result?.observations.map((observation) => (
        <View key={observation.id} style={styles.observation}>
          <Text selectable style={styles.observationText}>{observation.text}</Text>
          <Text style={styles.meta}>confidence: {observation.confidence.toFixed(4)}</Text>
          <Text style={styles.meta}>
            box: x {observation.boundingBox.x.toFixed(4)}, y {observation.boundingBox.y.toFixed(4)}, w {observation.boundingBox.width.toFixed(4)}, h {observation.boundingBox.height.toFixed(4)}
          </Text>
        </View>
      ))}
    </ScrollView>
  );
}

function ActionButton({ label, onPress, disabled = false, secondary = false, styles }: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  secondary?: boolean;
  styles: ReturnType<typeof createStyles>;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
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
    observation: { backgroundColor: theme.colors.secondarySurface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 4, padding: 10 },
    observationText: { color: theme.colors.text, fontSize: 15, fontWeight: "600" },
    optionCopy: { flex: 1, gap: 2 },
    optionRow: { alignItems: "center", flexDirection: "row", gap: 12, justifyContent: "space-between" },
    optionText: { color: theme.colors.text, fontSize: 15, textTransform: "capitalize" },
    pressed: { opacity: 0.75 },
    preview: { backgroundColor: theme.colors.secondarySurface, height: 280, width: "100%" },
    screen: { backgroundColor: theme.colors.background, flex: 1 },
    secondaryButton: { backgroundColor: theme.colors.secondarySurface, borderColor: theme.colors.border },
    sectionTitle: { color: theme.colors.text, fontSize: 17, fontWeight: "700" },
    segment: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 7, borderWidth: 1, flex: 1, minHeight: 42, padding: 10 },
    segmentSelected: { backgroundColor: theme.colors.activeBackground, borderColor: theme.colors.accent },
    segmented: { flexDirection: "row", gap: 8 },
    title: { color: theme.colors.text, fontSize: 30, fontWeight: "800", lineHeight: 36 },
  });
}
