import { Camera } from "expo-camera";
import * as FileSystem from "expo-file-system";
import * as ImagePicker from "expo-image-picker";
import { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Linking, StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../../../app/theme/AppTheme";
import {
  inspectImageQuality,
  recognizeTextFromImage,
} from "../../../native/ocr/NutritionOcr";
import { useNutritionRuntime } from "../../../runtime/NutritionRuntimeContext";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import { AccessibilityStatus } from "../../../shared/accessibility/AccessibilityStatus";
import { useAccessibilityAnnouncement } from "../../../shared/accessibility/announcements";
import {
  focusAccessibilityElement,
  useAccessibilityScreenFocus,
  type CancelAccessibilityFocus,
} from "../../../shared/accessibility/focus";
import type { NutritionConfirmationDraft } from "../api/types";
import {
  NutritionCameraCapture,
  type NutritionCameraCaptureResult,
} from "../components/NutritionCameraCapture";
import { draftFromParsedLabel } from "../confirmation/confirmationModel";
import {
  acquireOcrImage,
  deleteCameraCapture,
  type OcrImageSelection,
  type OcrImageSource,
} from "../diagnostics/diagnosticsModel";
import {
  imageQualityWarnings,
  type OcrImageQualityWarning,
} from "../quality/imageQuality";

type ScanStatus =
  | "idle"
  | "acquiring"
  | "camera"
  | "inspecting"
  | "quality_warning"
  | "recognizing"
  | "parsing"
  | "failure";

export function NutritionScanScreen({
  autoAcquireCamera = false,
  onCancel,
  onReady,
}: {
  autoAcquireCamera?: boolean;
  onCancel: () => void;
  onReady: (draft: NutritionConfirmationDraft) => void;
}) {
  const runtime = useNutritionRuntime();
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const [status, setStatus] = useState<ScanStatus>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [permissionDenied, setPermissionDenied] = useState(false);
  const [focusAfterCameraCancel, setFocusAfterCameraCancel] = useState(false);
  const [qualityWarnings, setQualityWarnings] = useState<
    readonly OcrImageQualityWarning[]
  >([]);

  const mounted = useRef(true);
  const requestId = useRef(0);
  const inFlight = useRef(false);
  const automaticCameraStarted = useRef(false);
  const cameraWasAutomaticRetake = useRef(false);
  const cameraSelection = useRef<OcrImageSelection | null>(null);
  const retakeCancelFocusRef = useRef<CancelAccessibilityFocus | null>(null);
  const headingRef = useRef<Text>(null);
  const qualityHeadingRef = useRef<Text>(null);
  const errorRef = useRef<Text>(null);
  const announce = useAccessibilityAnnouncement();

  useAccessibilityScreenFocus({
    active: status !== "camera",
    routeKey: "nutrition-scan",
    targetRef: headingRef,
  });

  useEffect(() => {
    if (!message) return;

    const cancelAnnouncement = announce(message, {
      key: "nutrition-scan-failure",
      kind: "error",
      priority: "assertive",
    });
    const cancelFocus = focusAccessibilityElement(errorRef.current, {
      focusKeyboardTarget: false,
    });

    return () => {
      cancelAnnouncement();
      cancelFocus();
    };
  }, [announce, message]);

  useEffect(() => {
    if (status !== "quality_warning" || qualityWarnings.length === 0) {
      return;
    }

    const summary = [
      "Photo quality warning.",
      ...qualityWarnings.map(({ message }) => message),
      "You can retake the photo or use the original photo anyway.",
    ].join(" ");

    const cancelAnnouncement = announce(summary, {
      key: "nutrition-image-quality-warning",
      priority: "assertive",
    });
    const cancelFocus = focusAccessibilityElement(
      qualityHeadingRef.current,
      {
        delayMs: 60,
        focusKeyboardTarget: false,
      },
    );

    return () => {
      cancelAnnouncement();
      cancelFocus();
    };
  }, [announce, qualityWarnings, status]);

  useEffect(() => {
    if (!focusAfterCameraCancel || status !== "idle") return;

    retakeCancelFocusRef.current?.();
    retakeCancelFocusRef.current = focusAccessibilityElement(
      headingRef.current,
      {
        delayMs: 60,
        focusKeyboardTarget: false,
      },
    );
    setFocusAfterCameraCancel(false);
  }, [focusAfterCameraCancel, status]);

  useEffect(() => {
    mounted.current = true;

    return () => {
      mounted.current = false;
      requestId.current += 1;
      retakeCancelFocusRef.current?.();
      retakeCancelFocusRef.current = null;
      void deleteCameraCapture(
        cameraSelection.current,
        (uri) => FileSystem.deleteAsync(uri, { idempotent: true }),
      );
      cameraSelection.current = null;
    };
  }, []);

  const processSelection = async (
    selection: OcrImageSelection,
    source: OcrImageSource,
    current: number,
  ) => {
    cameraSelection.current =
      selection.source === "camera" ? selection : null;

    try {
      setStatus("recognizing");
      const recognized = await recognizeTextFromImage(selection.uri);

      if (!mounted.current || current !== requestId.current) return;

      setStatus("parsing");
      const parsed = await runtime.ocr.parseNutritionLabel(recognized);

      if (!mounted.current || current !== requestId.current) return;

      onReady(draftFromParsedLabel(parsed, source));
    } catch {
      if (mounted.current && current === requestId.current) {
        setStatus("failure");
        setPermissionDenied(false);
        setMessage(
          "The nutrition label could not be recognized or parsed. Try a clearer image.",
        );
      }
    } finally {
      await deleteCameraCapture(
        cameraSelection.current,
        (uri) => FileSystem.deleteAsync(uri, { idempotent: true }),
      );
      cameraSelection.current = null;
      inFlight.current = false;
    }
  };

  const inspectCameraSelection = async (
    selection: OcrImageSelection,
    current: number,
  ) => {
    cameraSelection.current = selection;
    setStatus("inspecting");
    setQualityWarnings([]);

    let warnings: readonly OcrImageQualityWarning[] = [];

    try {
      const metrics = await inspectImageQuality(selection.uri);

      if (!mounted.current || current !== requestId.current) {
        await deleteCameraCapture(
          selection,
          (uri) => FileSystem.deleteAsync(uri, { idempotent: true }),
        );
        if (cameraSelection.current?.uri === selection.uri) {
          cameraSelection.current = null;
        }
        inFlight.current = false;
        return;
      }

      warnings = metrics ? imageQualityWarnings(metrics) : [];
    } catch {
      // Inspection is advisory. Any evaluator failure falls through to
      // recognition with the original image.
      warnings = [];
    }

    if (!mounted.current || current !== requestId.current) {
      await deleteCameraCapture(
        selection,
        (uri) => FileSystem.deleteAsync(uri, { idempotent: true }),
      );
      if (cameraSelection.current?.uri === selection.uri) {
        cameraSelection.current = null;
      }
      inFlight.current = false;
      return;
    }

    if (warnings.length > 0) {
      setQualityWarnings(warnings);
      setStatus("quality_warning");
      inFlight.current = false;
      return;
    }

    await processSelection(selection, "camera", current);
  };

  const acquirePhotoLibrary = async () => {
    if (inFlight.current) return;

    inFlight.current = true;
    const current = ++requestId.current;

    setStatus("acquiring");
    setMessage(null);
    setPermissionDenied(false);
    setQualityWarnings([]);

    const outcome = await acquireOcrImage("photo_library", {
      requestPermission: ImagePicker.requestMediaLibraryPermissionsAsync,
      launch: () =>
        ImagePicker.launchImageLibraryAsync({
          mediaTypes: ["images"],
          allowsEditing: false,
          quality: 1,
        }),
    });

    if (!mounted.current || current !== requestId.current) {
      inFlight.current = false;
      return;
    }

    if (outcome.kind !== "selected") {
      inFlight.current = false;
      setStatus(outcome.kind === "cancelled" ? "idle" : "failure");
      setPermissionDenied(outcome.kind === "permissionDenied");

      if (outcome.kind === "permissionDenied") {
        setMessage(
          "Photo access is required to choose a label image.",
        );
      }
      if (outcome.kind === "failed") {
        setMessage("The image could not be acquired. Try again.");
      }
      return;
    }

    await processSelection(
      outcome.selection,
      "photo_library",
      current,
    );
  };

  const openCamera = async (automaticRetake = false) => {
    if (inFlight.current || status === "camera") return;

    inFlight.current = true;
    const current = ++requestId.current;

    setStatus("acquiring");
    setMessage(null);
    setPermissionDenied(false);
    setQualityWarnings([]);

    try {
      const permission = await Camera.requestCameraPermissionsAsync();

      if (!mounted.current || current !== requestId.current) {
        return;
      }

      if (!permission.granted) {
        setStatus("failure");
        setPermissionDenied(true);
        setMessage("Camera access is required to take a label photo.");
        return;
      }

      cameraWasAutomaticRetake.current = automaticRetake;
      setStatus("camera");
    } catch {
      if (mounted.current && current === requestId.current) {
        setStatus("failure");
        setPermissionDenied(false);
        setMessage("The camera could not be opened. Try again.");
      }
    } finally {
      inFlight.current = false;
    }
  };

  const cancelCamera = () => {
    const wasAutomaticRetake = cameraWasAutomaticRetake.current;
    cameraWasAutomaticRetake.current = false;
    requestId.current += 1;

    setStatus("idle");
    setMessage(null);
    setPermissionDenied(false);
    setQualityWarnings([]);
    setFocusAfterCameraCancel(true);

    if (wasAutomaticRetake) {
      announce("Photo retake cancelled. Scan options are available.", {
        key: "nutrition-retake-cancelled",
        priority: "polite",
      });
    }
  };

  const retakeQualityCapture = async () => {
    if (inFlight.current) return;

    const selection = cameraSelection.current;

    inFlight.current = true;
    requestId.current += 1;
    setStatus("acquiring");
    setQualityWarnings([]);
    setMessage(null);
    setPermissionDenied(false);

    if (selection) {
      await deleteCameraCapture(
        selection,
        (uri) => FileSystem.deleteAsync(uri, { idempotent: true }),
      );

      if (cameraSelection.current?.uri === selection.uri) {
        cameraSelection.current = null;
      }
    }

    if (!mounted.current) {
      inFlight.current = false;
      return;
    }

    inFlight.current = false;
    await openCamera();
  };

  const useCameraPhotoAnyway = () => {
    if (inFlight.current) return;

    const selection = cameraSelection.current;
    if (!selection) {
      setQualityWarnings([]);
      setStatus("idle");
      return;
    }

    inFlight.current = true;
    setQualityWarnings([]);
    const current = ++requestId.current;

    void processSelection(selection, "camera", current);
  };

  const handleCameraCaptured = (
    capture: NutritionCameraCaptureResult,
  ) => {
    const selection: OcrImageSelection = {
      uri: capture.uri,
      width: capture.width,
      height: capture.height,
      source: "camera",
    };

    if (!mounted.current || inFlight.current) {
      void deleteCameraCapture(
        selection,
        (uri) => FileSystem.deleteAsync(uri, { idempotent: true }),
      );
      return;
    }

    inFlight.current = true;
    cameraWasAutomaticRetake.current = false;
    const current = ++requestId.current;

    void inspectCameraSelection(selection, current);
  };

  useEffect(() => {
    if (!autoAcquireCamera || automaticCameraStarted.current) return;

    automaticCameraStarted.current = true;
    void openCamera(true);
  }, [autoAcquireCamera]);

  if (status === "camera") {
    return (
      <NutritionCameraCapture
        onCancel={cancelCamera}
        onCaptured={handleCameraCaptured}
      />
    );
  }

  if (status === "quality_warning") {
    return (
      <View style={styles.screen}>
        <View style={styles.header}>
          <Text
            ref={qualityHeadingRef}
            accessibilityRole="header"
            style={styles.title}
          >
            Check photo quality
          </Text>

          <AccessiblePressable
            accessibilityLabel="Cancel label scan"
            onPress={onCancel}
          >
            <Text style={styles.link}>Cancel</Text>
          </AccessiblePressable>
        </View>

        <Text style={styles.body}>
          We found possible image-quality problems before text recognition.
          These checks are conservative, so you can still use the original
          photo.
        </Text>

        <View
          accessibilityLabel="Photo quality warnings"
          style={styles.warningPanel}
        >
          {qualityWarnings.map((warning) => (
            <Text
              key={warning.code}
              style={styles.warningText}
            >
              • {warning.message}
            </Text>
          ))}
        </View>

        <AccessiblePressable
          accessibilityLabel="Retake photo"
          accessibilityHint="Deletes this temporary photo and reopens the nutrition label camera"
          onPress={() => {
            void retakeQualityCapture();
          }}
          style={styles.button}
        >
          <Text style={styles.buttonText}>Retake photo</Text>
        </AccessiblePressable>

        <AccessiblePressable
          accessibilityLabel="Use photo anyway"
          accessibilityHint="Continues with on-device recognition using the original photo"
          onPress={useCameraPhotoAnyway}
          style={styles.secondaryButton}
        >
          <Text style={styles.secondaryButtonText}>Use photo anyway</Text>
        </AccessiblePressable>
      </View>
    );
  }

  const busy =
    status === "acquiring" ||
    status === "inspecting" ||
    status === "recognizing" ||
    status === "parsing";

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <Text
          ref={headingRef}
          accessibilityRole="header"
          style={styles.title}
        >
          Scan nutrition label
        </Text>

        <AccessiblePressable
          accessibilityLabel="Cancel label scan"
          disabled={busy}
          onPress={onCancel}
        >
          <Text style={styles.link}>Cancel</Text>
        </AccessiblePressable>
      </View>

      <Text style={styles.body}>
        Choose a still photo or take one now. Recognition runs on this device;
        only structured text is sent for parsing.
      </Text>

      <AccessiblePressable
        accessibilityLabel="Choose nutrition label photo"
        accessibilityHint="Opens the iOS photo library"
        disabled={busy}
        onPress={() => {
          void acquirePhotoLibrary();
        }}
        style={styles.button}
      >
        <Text style={styles.buttonText}>Choose photo</Text>
      </AccessiblePressable>

      <AccessiblePressable
        accessibilityLabel="Take nutrition label photo"
        accessibilityHint="Opens an in-app camera with Nutrition Facts framing guidance"
        disabled={busy}
        onPress={() => {
          void openCamera();
        }}
        style={styles.button}
      >
        <Text style={styles.buttonText}>Take photo</Text>
      </AccessiblePressable>

      {busy ? (
        <View style={styles.progress}>
          <ActivityIndicator accessibilityLabel="Label scan in progress" />
          <AccessibilityStatus
            kind="busy"
            message={
              status === "acquiring"
                ? "Opening image source…"
                : status === "inspecting"
                  ? "Checking photo quality…"
                  : status === "recognizing"
                    ? "Recognizing label text…"
                    : "Parsing nutrition values…"
            }
          />
        </View>
      ) : null}

      {message ? (
        <Text
          ref={errorRef}
          accessibilityLiveRegion="none"
          accessibilityRole="alert"
          style={styles.error}
        >
          {message}
        </Text>
      ) : null}

      {permissionDenied ? (
        <AccessiblePressable
          accessibilityLabel="Open app settings"
          accessibilityHint="Opens iOS Settings so camera or photo access can be changed"
          onPress={() => {
            void Linking.openSettings();
          }}
          style={styles.settingsButton}
        >
          <Text style={styles.settingsButtonText}>Open Settings</Text>
        </AccessiblePressable>
      ) : null}
    </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    body: {
      color: theme.colors.secondaryText,
      fontSize: 15,
      lineHeight: 21,
    },
    button: {
      alignItems: "center",
      backgroundColor: theme.colors.primaryActionBackground,
      borderRadius: 8,
      minHeight: 48,
      justifyContent: "center",
    },
    buttonText: {
      color: theme.colors.primaryActionForeground,
      fontSize: 16,
      fontWeight: "700",
    },
    error: {
      color: theme.colors.errorText,
    },
    header: {
      alignItems: "center",
      flexDirection: "row",
      flexWrap: "wrap",
      justifyContent: "space-between",
    },
    link: {
      color: theme.colors.accent,
      fontSize: 16,
    },
    progress: {
      alignItems: "center",
      flexDirection: "row",
      gap: 10,
    },
    screen: {
      backgroundColor: theme.colors.background,
      flex: 1,
      gap: 16,
      padding: 16,
    },
    secondaryButton: {
      alignItems: "center",
      borderColor: theme.colors.border,
      borderRadius: 8,
      borderWidth: 1,
      minHeight: 48,
      justifyContent: "center",
    },
    secondaryButtonText: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: "700",
    },
    settingsButton: {
      alignItems: "center",
      borderColor: theme.colors.border,
      borderRadius: 8,
      borderWidth: 1,
      minHeight: 44,
      justifyContent: "center",
      paddingHorizontal: 12,
    },
    settingsButtonText: {
      color: theme.colors.accent,
      fontWeight: "700",
    },
    warningPanel: {
      borderColor: theme.colors.border,
      borderRadius: 8,
      borderWidth: 1,
      gap: 10,
      padding: 12,
    },
    warningText: {
      color: theme.colors.text,
      fontSize: 15,
      lineHeight: 21,
    },
    title: {
      color: theme.colors.text,
      fontSize: 26,
      fontWeight: "800",
    },
  });
}
